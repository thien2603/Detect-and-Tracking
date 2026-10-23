"""Publish local files as independent clock-marked RTSP sources; Ctrl+C stops all."""

import argparse
import logging
import signal
import time
from pathlib import Path
from threading import Event, Thread

import cv2

from app.camera.capture import CameraCapture
from app.config.loader import load_config
from app.config.schemas import StreamingConfig
from app.streaming.publisher import FFmpegPublisher
from app.telemetry import console_logging, stamp_time
from scripts.prepare_realtime_config import build_config

LOGGER = logging.getLogger(__name__)


class Replay:
    def __init__(self, camera, server, ffmpeg, fps=15, stamp=True):
        self.capture = CameraCapture(camera)
        settings = StreamingConfig(enabled=True, ffmpeg_bin=ffmpeg, output_fps=fps,
                                   rtsp_server=server, max_frame_age_ms=800)
        self.publisher = FFmpegPublisher(settings, "source/" + camera.id)
        self.stop_event = Event()
        self.stamp = stamp
        self.fps = fps
        self.thread = Thread(target=self.run, name=f"replay-{camera.id}", daemon=True)
        self.capture.start()
        self.thread.start()

    def run(self):
        sequence = 0
        while not self.stop_event.is_set():
            latest = self.capture.get_latest(sequence)
            if latest:
                sequence, frame, _, captured_at = latest
                frame = frame.copy()
                if self.stamp:
                    origin = time.time() * 1000 - (time.monotonic() - captured_at) * 1000
                    stamp_time(frame, origin)
                self.publisher.submit(frame)
            self.stop_event.wait(1 / self.fps)

    def close(self):
        self.stop_event.set()
        self.thread.join(timeout=3)
        self.capture.close()
        self.publisher.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="configs/bellevue.yaml")
    parser.add_argument("--server", default="rtsp://127.0.0.1:8554")
    parser.add_argument("--ffmpeg", default="ffmpeg")
    parser.add_argument("--fps", type=float, default=15)
    parser.add_argument("--count", type=int, help="Default: every camera declared in the YAML")
    parser.add_argument("--stop-file", type=Path)
    args = parser.parse_args()
    if not 10 <= args.fps <= 30:
        parser.error("Replay FPS must be 10..30")
    console_logging()
    base = load_config(args.config)
    cv2.setNumThreads(base.model.opencv_threads)
    from app.config.schemas import AppConfig

    config = AppConfig.model_validate(build_config(base, args.count))
    stopped = Event()
    signal.signal(signal.SIGINT, lambda *_: stopped.set())
    signal.signal(signal.SIGTERM, lambda *_: stopped.set())
    replays = []
    try:
        for camera in config.cameras:
            if camera.source.type != "file":
                raise ValueError("Replay input must be a local file configuration")
            replays.append(Replay(camera, args.server, args.ffmpeg, args.fps))
        LOGGER.info("Publishing %d independent replay sources", len(replays))
        while not stopped.wait(0.2):
            if args.stop_file and args.stop_file.exists():
                break
    finally:
        for replay in replays:
            replay.close()
        LOGGER.info("All replay capture/publisher threads stopped")


if __name__ == "__main__":
    main()
