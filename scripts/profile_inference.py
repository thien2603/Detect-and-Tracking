"""Isolate model startup/inference from the RTSP/annotation workload."""

import argparse
import faulthandler
import json
import time
from pathlib import Path

import cv2
import psutil

from app.config.loader import load_config
from app.inference.detector import YOLODetector
from app.inference.scheduler import InferenceScheduler


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="configs/submission-efficient.yaml")
    parser.add_argument("--half", action="store_true")
    parser.add_argument("--threaded", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    config = load_config(args.config)
    config.model.half = args.half
    cv2.setNumThreads(1)
    report = {"half_requested": args.half, "threaded": args.threaded,
              "free_ram_mb_before": psutil.virtual_memory().available / 1024**2}
    scheduler = None
    faulthandler.dump_traceback_later(20, repeat=True)
    try:
        frames = []
        for camera in config.cameras:
            capture = cv2.VideoCapture(str(camera.source.uri), cv2.CAP_FFMPEG,
                                       [cv2.CAP_PROP_N_THREADS, 1])
            try:
                ok, frame = capture.read()
                if not ok:
                    raise RuntimeError(f"Cannot read {camera.id}")
                frames.append(frame)
            finally:
                capture.release()
        detector = YOLODetector(config.model)
        began = time.perf_counter()
        detector.load()
        report["load_ms"] = (time.perf_counter() - began) * 1000
        print("model_loaded", report["load_ms"], flush=True)
        if args.threaded:
            scheduler = InferenceScheduler(detector, len(frames), 5)
        measurements = []
        for _ in range(6):
            began = time.perf_counter()
            if scheduler:
                futures = [scheduler.submit(str(i), frame) for i, frame in enumerate(frames)]
                results = [future.result(timeout=60) for future in futures]
            else:
                results = detector.detect_batch(frames)
            elapsed = (time.perf_counter() - began) * 1000
            measurements.append(elapsed)
            print("batch_ms", round(elapsed, 2), "boxes", [len(r) for r in results], flush=True)
        report.update(batch_ms=measurements, frames_per_batch=len(frames),
                      precision_options=detector._precision,
                      peak_rss_mb=getattr(psutil.Process().memory_info(), "peak_wset",
                                          psutil.Process().memory_info().rss) / 1024**2)
        report["status"] = "completed"
    except Exception as exc:
        report.update(status="failed", error=repr(exc))
        raise
    finally:
        if scheduler:
            scheduler.close()
        faulthandler.cancel_dump_traceback_later()
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
