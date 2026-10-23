"""Render all four approved Bellevue cameras with one shared YOLO model."""

from __future__ import annotations

import argparse
import json
import logging
import shutil
from pathlib import Path

from app.config.loader import load_config
from app.inference.detector import YOLODetector
from app.telemetry import console_logging
from scripts.render_video import render

LOGGER = logging.getLogger(__name__)


ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=ROOT / "configs/bellevue.yaml")
    parser.add_argument("--output", type=Path, default=ROOT / "data/renders/bellevue")
    parser.add_argument("--ffmpeg", required=True)
    parser.add_argument("--fps", type=float, default=30)
    parser.add_argument("--max-seconds", type=float)
    parser.add_argument("--device", default="0")
    args = parser.parse_args()
    console_logging()
    if not 1 <= args.fps <= 60:
        parser.error("FPS must be 1..60")
    if args.max_seconds is not None and args.max_seconds <= 0:
        parser.error("max-seconds must be positive")
    config = load_config(args.config)
    config.streaming.ffmpeg_bin = args.ffmpeg
    config.model.device = args.device
    args.output = args.output.resolve()
    args.output.mkdir(parents=True, exist_ok=True)
    summary_path = args.output / "summary.json"
    if summary_path.exists():
        raise FileExistsError(f"Existing result: {summary_path}")
    for camera in config.cameras:
        if any(args.output.glob(f"{camera.id}-tracking*")):
            raise FileExistsError(f"Existing output for {camera.id}; choose a new folder")
    if shutil.disk_usage(args.output).free < 600 * 1024 * 1024:
        raise RuntimeError("At least 600 MB free is required for four renders and snapshots")
    detector = YOLODetector(config.model)
    detector.load()
    results = []
    for index, camera in enumerate(config.cameras, 1):
        output = args.output / f"{camera.id}-tracking.mp4"
        LOGGER.info("[%d/%d] Rendering %s", index, len(config.cameras), camera.id)
        payload = render(config, camera, output, detector, args.fps, args.max_seconds)
        result = {
            "camera_id": camera.id,
            "output": str(output),
            "events": str(output.with_suffix(".events.json")),
            "duration_seconds": payload["duration_seconds"],
            "fps": payload["fps"],
            "frames": payload["frames"],
            "counts": payload["counts"],
            "zone_alerts": sum(e["event_type"] == "intrusion" for e in payload["events"]),
            "zone_entries": sum(e["event_type"] == "intrusion"
                                and e["metadata"]["reason"] == "entry"
                                for e in payload["events"]),
        }
        results.append(result)
        LOGGER.info("[%s] Saved %s; entries=%d, alerts=%d", camera.id, output,
                    result["counts"]["region_entries"], result["zone_alerts"])
        summary_path.write_text(json.dumps({
            "model": config.model.weights,
            "classes": config.model.classes,
            "device": config.model.device,
            "counting": "One observed outside-to-inside transition per track ID. "
                        "First-seen-inside is separate; ID fragmentation can affect totals.",
            "alerts": "Geometric demonstration zones, not traffic-law findings.",
            "results": results,
        }, indent=2) + "\n", encoding="utf-8")
    LOGGER.info("All %d cameras complete. Summary: %s", len(results), summary_path)


if __name__ == "__main__":
    main()
