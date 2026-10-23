import argparse
import logging
from pathlib import Path

from app.telemetry import console_logging

LOGGER = logging.getLogger(__name__)

def main():
    console_logging()
    parser = argparse.ArgumentParser(description="Download an official Ultralytics model")
    parser.add_argument("--output", default="models/yolo11n.pt")
    args = parser.parse_args()
    path = Path(args.output).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    from ultralytics import YOLO
    from ultralytics.utils.downloads import attempt_download_asset

    downloaded = Path(attempt_download_asset(str(path)))
    if not downloaded.is_file():
        raise RuntimeError(f"Weight download failed: {path}")
    YOLO(str(downloaded))
    LOGGER.info("Model ready: %s", downloaded)


if __name__ == "__main__":
    main()
