"""Verify actual YOLO person/vehicle detections on sparse samples, not unique-person counts."""

import argparse
import json
import logging
from collections import Counter
from pathlib import Path

import cv2

from app.config.loader import load_config
from app.config.preflight import validate_runtime
from app.inference.detector import YOLODetector
from app.pipeline import AnalyticsPipeline
from app.telemetry import console_logging

LOGGER = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="configs/people.yaml")
    parser.add_argument("--output", type=Path,
                        default=Path("data/verification/people-detection.json"))
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError("Choose a new verification output")
    console_logging()
    config = load_config(args.config)
    validate_runtime(config)
    camera = config.cameras[0]
    capture = cv2.VideoCapture(camera.source.uri, cv2.CAP_FFMPEG, [cv2.CAP_PROP_N_THREADS, 1])
    frames, times = [], [0, 30, 60, 90, 120, 150, 179]
    try:
        for seconds in times:
            capture.set(cv2.CAP_PROP_POS_MSEC, seconds * 1000)
            ok, frame = capture.read()
            if not ok:
                raise RuntimeError(f"Cannot read sample at {seconds}s")
            frames.append(frame)
    finally:
        capture.release()
    detector = YOLODetector(config.model)
    counts, samples = Counter(), []
    args.output.parent.mkdir(parents=True, exist_ok=True)
    images = args.output.parent / "people-samples"
    images.mkdir(exist_ok=True)
    for start in range(0, len(frames), config.model.batch_size):
        detections = detector.detect_batch(frames[start:start + config.model.batch_size])
        for index, boxes in enumerate(detections, start):
            counts.update(box.class_name for box in boxes)
            # Reset identity for each sparse sample; never infer crossings across 30s gaps.
            canvas, _, _ = AnalyticsPipeline(camera).process(
                frames[index], boxes, times[index], video_seconds=times[index])
            image_path = images / f"sample-{times[index]:03}s.jpg"
            if not cv2.imwrite(str(image_path), canvas):
                raise OSError("Cannot save detection preview")
            samples.append({"seconds": times[index], "class_counts": dict(Counter(
                box.class_name for box in boxes)), "preview": str(image_path.resolve())})
    report = {"source": camera.source.uri, "model": config.model.weights,
              "classes": config.model.classes, "confidence": config.model.confidence,
              "imgsz": config.model.imgsz, "device": config.model.device,
              "class_counts": dict(counts), "samples": samples,
              "note": "Summed box detections in sparse samples, not unique people/traffic counts"}
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    LOGGER.info("Actual sampled YOLO detections: %s", dict(counts))
    if counts["person"] == 0:
        raise RuntimeError("No person detected in verification samples")


if __name__ == "__main__":
    main()
