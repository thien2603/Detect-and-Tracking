from __future__ import annotations

import logging
import time
from threading import Event, Lock, Thread

import cv2

LOGGER = logging.getLogger(__name__)


class CameraCapture:
    """Single-slot latest-frame buffer; file playback follows source frame timestamps."""

    def __init__(self, camera):
        self.camera = camera
        self.stop_event = Event()
        self.lock = Lock()
        self.latest = None
        self.sequence = 0
        self.eof = False
        self.error = None
        self.capture = None
        self.open_attempts = 0
        self.reconnect_count = 0
        self.frames_read = 0
        self.thread = Thread(target=self._run, name=f"capture-{camera.id}", daemon=True)

    def start(self):
        self.thread.start()

    def get_latest(self, after_sequence):
        with self.lock:
            if self.latest is None or self.sequence <= after_sequence:
                return None
            return (self.sequence, *self.latest)

    def _open(self):
        source = self.camera.source
        uri = int(source.uri) if source.type == "webcam" else str(source.uri)
        if source.type == "rtsp":
            return cv2.VideoCapture(
                uri,
                cv2.CAP_FFMPEG,
                [
                    cv2.CAP_PROP_OPEN_TIMEOUT_MSEC,
                    3000,
                    cv2.CAP_PROP_READ_TIMEOUT_MSEC,
                    3000,
                    cv2.CAP_PROP_N_THREADS,
                    1,
                ],
            )
        if source.type == "file":
            return cv2.VideoCapture(uri, cv2.CAP_FFMPEG, [cv2.CAP_PROP_N_THREADS, 1])
        return cv2.VideoCapture(uri)

    def _run(self):
        source = self.camera.source
        while not self.stop_event.is_set():
            cap = None
            try:
                if self.open_attempts and source.type != "file":
                    self.reconnect_count += 1
                    LOGGER.warning("camera=%s reconnect=%d", self.camera.id, self.reconnect_count)
                self.open_attempts += 1
                cap = self._open()
                self.capture = cap
                if not cap.isOpened():
                    self.error = f"Cannot open camera {self.camera.id}"
                    cap.release()
                    if source.type == "file":
                        return
                    self.stop_event.wait(source.reconnect_seconds)
                    continue
                fps = cap.get(cv2.CAP_PROP_FPS)
                fps = fps if 0 < fps <= 240 else 25.0
                started, index = time.monotonic(), 0
                self.error = None
                LOGGER.info("camera=%s connected source_type=%s", self.camera.id, source.type)
                while not self.stop_event.is_set():
                    ok, frame = cap.read()
                    if not ok:
                        break
                    seconds = index / fps if source.type == "file" else time.monotonic() - started
                    if source.type == "file":
                        self.stop_event.wait(max(0, started + seconds - time.monotonic()))
                    if self.stop_event.is_set():
                        break
                    with self.lock:
                        self.sequence += 1
                        self.frames_read += 1
                        self.latest = (frame, seconds, time.monotonic())
                    index += 1
                cap.release()
                self.capture = None
                if source.type == "file" and not source.loop:
                    self.eof = True
                    return
                if source.type != "file":
                    self.error = "Stream disconnected; reconnecting"
                    self.stop_event.wait(source.reconnect_seconds)
                elif index == 0:
                    self.error = "No readable frames in file"
                    self.stop_event.wait(source.reconnect_seconds)
            except Exception as exc:
                self.error = str(exc)
                LOGGER.exception("Capture failed: %s", self.camera.id)
                if source.type == "file":
                    return
                self.stop_event.wait(source.reconnect_seconds)
            finally:
                if cap is not None:
                    cap.release()
                self.capture = None

    def close(self):
        self.stop_event.set()
        # RTSP reads/open operations have a 3-second native timeout.
        self.thread.join(timeout=8)
        if self.thread.is_alive():
            LOGGER.error("Capture did not stop in time: %s", self.camera.id)
