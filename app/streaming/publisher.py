from __future__ import annotations

import contextlib
import logging
import subprocess
import time
from functools import lru_cache
from queue import Empty, Full, Queue
from threading import Event, Lock, Thread

import cv2

from app.telemetry import read_time, stamp_time

LOGGER = logging.getLogger(__name__)
ENCODER_PROBE_LOCK = Lock()


def encoder_arguments(encoder, preset="ultrafast"):
    if encoder == "h264_nvenc":
        # llhp is understood by both the driver-compatible FFmpeg 4.2 and 7.x.
        return ["-c:v", encoder, "-preset", "llhp", "-zerolatency", "1",
                "-rc-lookahead", "0", "-bf", "0", "-b:v", "3M",
                "-maxrate", "3M", "-bufsize", "300k"]
    return ["-c:v", "libx264", "-threads", "1", "-preset", preset,
            "-tune", "zerolatency"]


@lru_cache(maxsize=8)
def probe_nvenc(ffmpeg):
    """Exercise the encoder; listing '-encoders' cannot detect driver mismatch."""
    try:
        result = subprocess.run([
            ffmpeg, "-hide_banner", "-v", "error", "-f", "lavfi", "-i",
            "color=c=black:s=640x360:r=10", "-frames:v", "1",
            *encoder_arguments("h264_nvenc"), "-f", "null", "-",
        ], capture_output=True, timeout=10)
        return result.returncode == 0, result.stderr.decode(errors="replace")[-1500:]
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, str(exc)


def prepare_output_frame(frame, config):
    """Resize only the annotated output; input geometry/tracking coordinates stay unchanged."""
    origin = read_time(frame) if config.timestamp_overlay else None
    height, width = frame.shape[:2]
    ratio = min(1, (config.max_output_width or width) / width,
                (config.max_output_height or height) / height)
    if ratio < 1:
        dimensions = (max(2, int(width * ratio) // 2 * 2),
                      max(2, int(height * ratio) // 2 * 2))
        frame = cv2.resize(frame, dimensions, interpolation=cv2.INTER_AREA)
        if origin is not None:
            stamp_time(frame, origin)  # Preserve the original clock, never use a new timestamp.
    else:
        frame = frame.copy()
    return frame, origin


class FFmpegPublisher:
    """Latest-frame RTSP output with stale-frame cutoff and blocked-write watchdog."""

    def __init__(self, config, path):
        self.config, self.path = config, path
        self.queue = Queue(maxsize=1)
        self.stop_event = Event()
        self.process = None
        self.writing_since = None
        self.error = None
        self.frames = 0
        self.unique_frames = 0
        self.restarts = 0
        self.start_attempts = 0
        self.encoder = None
        self.encoder_diagnostic = None
        self.stderr_thread = None
        self.thread = Thread(target=self._run, name=f"publish-{path}", daemon=True)
        self.watchdog = Thread(target=self._watch, name=f"ffmpeg-watch-{path}", daemon=True)
        self.thread.start()
        self.watchdog.start()

    def submit(self, frame):
        frame, origin = prepare_output_frame(frame, self.config)
        candidate = (frame, time.monotonic(), origin)
        try:
            self.queue.put_nowait(candidate)
        except Full:
            with contextlib.suppress(Empty):
                self.queue.get_nowait()
            with contextlib.suppress(Full):
                self.queue.put_nowait(candidate)

    def _start(self, frame):
        if self.encoder is None:
            self.encoder = self.config.encoder
            if self.encoder == "auto":
                with ENCODER_PROBE_LOCK:
                    supported, diagnostic = probe_nvenc(self.config.ffmpeg_bin)
                self.encoder = "h264_nvenc" if supported else "libx264"
                self.encoder_diagnostic = diagnostic or None
            LOGGER.info("publisher=%s encoder=%s", self.path, self.encoder)
        self.start_attempts += 1
        self.restarts = self.start_attempts - 1
        if self.restarts:
            LOGGER.warning("publisher=%s restarting count=%d", self.path, self.restarts)
        height, width = frame.shape[:2]
        uri = self.config.rtsp_server.rstrip("/") + "/" + self.path
        self.process = subprocess.Popen(
            [
                self.config.ffmpeg_bin,
                "-v",
                "error",
                "-nostdin",
                "-filter_threads",
                "1",
                "-filter_complex_threads",
                "1",
                "-f",
                "rawvideo",
                "-pix_fmt",
                "bgr24",
                "-s",
                f"{width}x{height}",
                "-r",
                str(self.config.output_fps),
                "-i",
                "-",
                "-an",
                *encoder_arguments(self.encoder, self.config.preset),
                "-pix_fmt",
                "yuv420p",
                "-g",
                str(round(self.config.output_fps)),
                "-f",
                "rtsp",
                "-rtsp_transport",
                "tcp",
                uri,
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        pipe = self.process.stderr

        def read_errors():
            for line in iter(pipe.readline, b""):
                message = line.decode(errors="replace").strip()
                if message:
                    self.encoder_diagnostic = message[-1500:]
                    LOGGER.warning("publisher=%s ffmpeg: %s", self.path, message)

        self.stderr_thread = Thread(target=read_errors, name="publisher-stderr", daemon=True)
        self.stderr_thread.start()

    def _kill(self):
        process = self.process
        if process:
            if process.poll() is None:
                process.kill()
            with contextlib.suppress(subprocess.TimeoutExpired):
                process.wait(timeout=3)
            if process.stdin:
                with contextlib.suppress(OSError):
                    process.stdin.close()
            if self.stderr_thread:
                self.stderr_thread.join(timeout=2)
                self.stderr_thread = None
            if process.stderr:
                process.stderr.close()
            if self.process is process:
                self.process = None

    def _watch(self):
        while not self.stop_event.wait(0.2):
            started, process = self.writing_since, self.process
            if started is not None and time.monotonic() - started > 3 and process:
                self.error = "FFmpeg blocked while publishing; restarting"
                if process.poll() is None:
                    process.kill()

    def _fallback_encoder(self, reason):
        if self.config.encoder == "auto" and self.encoder == "h264_nvenc":
            self.encoder = "libx264"
            LOGGER.warning("publisher=%s NVENC failed; falling back to CPU: %s",
                           self.path, self.encoder_diagnostic or reason)

    def _run(self):
        cached = None
        interval = 1 / self.config.output_fps
        due = time.monotonic()
        try:
            while not self.stop_event.is_set():
                fresh = False
                try:
                    cached = self.queue.get(timeout=max(0.001, due - time.monotonic()))
                    fresh = True
                except Empty:
                    pass
                if cached is None:
                    due = time.monotonic() + interval
                    continue
                if self.stop_event.wait(max(0, due - time.monotonic())):
                    break
                frame, timestamp, origin = cached
                due = time.monotonic() + interval
                if (time.monotonic() - timestamp) * 1000 > self.config.max_frame_age_ms:
                    continue
                if (origin is not None
                        and time.time() * 1000 - origin > self.config.max_frame_age_ms):
                    continue
                try:
                    if self.process is None or self.process.poll() is not None:
                        failed = self.process is not None and self.process.returncode != 0
                        self._kill()
                        if failed:
                            self._fallback_encoder("FFmpeg exited unsuccessfully")
                        self._start(frame)
                    self.writing_since = time.monotonic()
                    self.process.stdin.write(frame.tobytes())
                    self.process.stdin.flush()
                    self.frames += 1
                    self.unique_frames += int(fresh)
                    self.error = None
                except (OSError, ValueError) as exc:
                    self.error = str(exc)
                    self._kill()
                    self._fallback_encoder(exc)
                    self.stop_event.wait(1)
                finally:
                    self.writing_since = None
        finally:
            self._kill()

    def close(self):
        self.stop_event.set()
        process = self.process
        if process and process.poll() is None:
            process.kill()
        self.thread.join(timeout=8)
        self.watchdog.join(timeout=2)
