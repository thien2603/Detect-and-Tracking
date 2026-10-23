"""Create a four-source config: three approved Bellevue cameras plus Crosswalk people."""

import argparse
from pathlib import Path

import yaml

from app.config.schemas import AppConfig
from app.telemetry import console_logging
from scripts.prepare_realtime_config import ROOT, save_config


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "configs/submission-four.yaml")
    parser.add_argument("--efficient", action="store_true",
                        help="Experiment: imgsz=480, smaller output; source unchanged")
    parser.add_argument("--optimized", action="store_true",
                        help="Also enable async rendering, Kalman predictions, FP16, encoder auto")
    args = parser.parse_args()
    console_logging()
    data = yaml.safe_load((ROOT / "configs/bellevue.yaml").read_text(encoding="utf-8"))
    people = yaml.safe_load((ROOT / "configs/people.yaml").read_text(encoding="utf-8"))
    # Retain the existing Bellevue configs unchanged; omit the most occluded view here.
    data["cameras"] = [camera for camera in data["cameras"] if camera["id"] != "cam03-se38th"]
    data["cameras"].extend(people["cameras"])
    data["database"] = {"path": "data/database/submission.db",
                        "snapshot_dir": "data/snapshots/submission"}
    data["logging"]["file"] = "logs/submission.log"
    if args.efficient or args.optimized:
        data["model"]["imgsz"] = 480
        data["streaming"].update(max_output_width=960, max_output_height=540,
                                 max_frame_age_ms=700)
    if args.optimized:
        data["model"].update(async_inference=True, detect_interval=2, half=True,
                             batch_size=4, batch_wait_ms=15, rect=False)
        data["streaming"]["output_fps"] = 14
        data["streaming"]["encoder"] = "auto"
        for camera in data["cameras"]:
            camera.update(tracker_motion=True, prediction_max_age_ms=700)
    AppConfig.model_validate(data)
    save_config(data, args.output)


if __name__ == "__main__":
    main()
