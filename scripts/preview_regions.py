import argparse
import logging
from pathlib import Path

import cv2

from app.config.loader import load_config
from app.inference.detector import YOLODetector
from app.pipeline import AnalyticsPipeline
from app.telemetry import console_logging

LOGGER = logging.getLogger(__name__)


def main():
    console_logging()
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="configs/vietnam-expressway.yaml")
    parser.add_argument("--seconds", type=float, default=60)
    parser.add_argument("--output", default="docs/region-preview.jpg")
    args = parser.parse_args()
    config = load_config(args.config)
    camera = config.cameras[0]
    if camera.source.type != "file":
        parser.error("Preview requires a file camera")
    capture = cv2.VideoCapture(str(camera.source.uri))
    capture.set(cv2.CAP_PROP_POS_MSEC, args.seconds * 1000)
    ok, frame = capture.read()
    capture.release()
    if not ok:
        raise RuntimeError("Cannot read preview frame")
    pipeline = AnalyticsPipeline(camera)
    canvas, _, _ = pipeline.process(
        frame,
        YOLODetector(config.model).detect_batch([frame])[0],
        args.seconds,
        video_seconds=args.seconds,
    )
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    if not cv2.imwrite(args.output, canvas):
        raise OSError("Cannot save preview")
    LOGGER.info("Preview: %s", args.output)


if __name__ == "__main__":
    main()
