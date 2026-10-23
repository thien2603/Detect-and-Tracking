"""Observe decoded RTSP output FPS and replay-source-to-decoder latency."""

import contextlib
import subprocess
import time
from threading import Event, Lock, Thread

import cv2
import numpy as np

from app.telemetry import read_time


def read_ppm(stream):
    """Read one lossless PPM frame from FFmpeg, preserving the clock marker."""
    magic = stream.readline()
    if not magic:
        return None
    if magic.strip() != b"P6":
        raise ValueError("Invalid FFmpeg PPM header")
    dimensions = stream.readline()
    while dimensions.startswith(b"#"):
        dimensions = stream.readline()
    width, height = map(int, dimensions.split())
    if not (0 < width * height <= 40_000_000) or stream.readline().strip() != b"255":
        raise ValueError("Unsupported PPM dimensions or depth")
    size = width * height * 3
    data = stream.read(size)
    if len(data) != size:
        raise OSError("FFmpeg ended during a PPM frame")
    return np.frombuffer(data, np.uint8).reshape(height, width, 3)[:, :, ::-1]


class RTSPProbe:
    def __init__(self, uri, *, ffmpeg=None, measure_latency=True):
        self.uri = uri
        self.ffmpeg = ffmpeg
        self.measure_latency = measure_latency
        self.process = None
        self.last_error = None
        self.stop_event = Event()
        self.lock = Lock()
        self.samples = []
        self.errors = 0
        self.last_frame = None
        self.thread = Thread(target=self.run_ffmpeg if ffmpeg else self.run,
                             name="rtsp-probe", daemon=True)
        self.thread.start()

    def run(self):
        while not self.stop_event.is_set():
            capture = cv2.VideoCapture(self.uri, cv2.CAP_FFMPEG, [
                cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 3000,
                cv2.CAP_PROP_READ_TIMEOUT_MSEC, 2000,
                cv2.CAP_PROP_N_THREADS, 1,
            ])
            try:
                while not self.stop_event.is_set():
                    ok, frame = capture.read()
                    if not ok:
                        self.errors += 1
                        break
                    self.record(frame)
            finally:
                capture.release()
            self.stop_event.wait(0.2)

    def record(self, frame):
        received = time.monotonic()
        timestamp = read_time(frame) if self.measure_latency else None
        latency = time.time() * 1000 - timestamp if timestamp else None
        with self.lock:
            self.samples.append((received, timestamp, latency))
            self.last_frame = frame

    def run_ffmpeg(self):
        # Independent decoder processes avoid OpenCV's global capture-open lock
        # serializing the probes and starving other readers during RTSP startup.
        while not self.stop_event.is_set():
            process = None
            error_reader = None
            try:
                process = subprocess.Popen([
                    self.ffmpeg, "-v", "error", "-nostdin", "-rtsp_transport", "tcp",
                    "-filter_threads", "1", "-filter_complex_threads", "1",
                    "-timeout", "4000000", "-fflags", "nobuffer", "-flags", "low_delay",
                    "-analyzeduration", "100000", "-probesize", "32768", "-threads", "1",
                    "-i", self.uri, "-map", "0:v:0", "-an", "-sn", "-dn", "-threads", "1",
                    "-fps_mode", "passthrough", "-c:v", "ppm", "-f", "image2pipe", "pipe:1",
                ], stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=1024 * 1024)
                self.process = process

                def read_errors(pipe):
                    for line in iter(pipe.readline, b""):
                        self.last_error = line.decode("utf-8", errors="replace").strip()[:500]

                error_reader = Thread(target=read_errors, args=(process.stderr,),
                                      name="probe-stderr", daemon=True)
                error_reader.start()
                while not self.stop_event.is_set():
                    frame = read_ppm(process.stdout)
                    if frame is None:
                        break
                    self.record(frame)
            except (OSError, ValueError) as exc:
                self.last_error = str(exc)
            finally:
                if process:
                    if process.poll() is None:
                        process.kill()
                    with contextlib.suppress(subprocess.TimeoutExpired):
                        process.wait(timeout=3)
                    if error_reader:
                        error_reader.join(timeout=2)
                    process.stdout.close()
                    process.stderr.close()
                self.process = None
            if not self.stop_event.is_set():
                self.errors += 1
                self.stop_event.wait(0.2)

    def report(self, start, end):
        with self.lock:
            samples = [sample for sample in self.samples if start <= sample[0] <= end]
        latency = [sample[2] for sample in samples if sample[2] is not None]
        origins = {sample[1] for sample in samples if sample[1] is not None}
        return {
            "probe_backend": "ffmpeg_tcp_ppm" if self.ffmpeg else "opencv",
            "last_probe_error": self.last_error,
            "decoded_frames": len(samples), "decoded_fps": len(samples) / (end - start),
            "unique_source_fps": len(origins) / (end - start),
            "timestamp_samples": len(latency), "decode_errors": self.errors,
            "latency_p50_ms": float(np.percentile(latency, 50)) if latency else None,
            "latency_p95_ms": float(np.percentile(latency, 95)) if latency else None,
            "latency_max_ms": max(latency) if latency else None,
            "latency_basis": "File-replay capture to decoded RTSP output, same-host clock; "
                             "excludes physical camera exposure and VLC display buffering",
        }

    def close(self):
        self.stop_event.set()
        process = self.process
        if process and process.poll() is None:
            process.kill()
        self.thread.join(timeout=8)
        if self.thread.is_alive():
            raise RuntimeError("RTSP probe did not stop")
