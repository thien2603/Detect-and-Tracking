"""Decode rendered Bellevue videos and cross-check event evidence."""

import argparse
import json
import logging
import sqlite3
from pathlib import Path

import cv2
import numpy as np

from app.telemetry import console_logging

LOGGER = logging.getLogger(__name__)

def verify(directory):
    summary = json.loads((directory / "summary.json").read_text())
    if len(summary["results"]) != 4:
        raise ValueError("Expected four completed cameras")
    records, thumbnails = [], []
    for result in summary["results"]:
        video = Path(result["output"])
        events_file = Path(result["events"])
        payload = json.loads(events_file.read_text())
        events = payload["events"]
        entries = [event for event in events if event["event_type"] == "region_entry"]
        if len(entries) != result["counts"]["region_entries"]:
            raise ValueError("Counter and entry-event count differ")
        if len({event["track_id"] for event in entries}) != len(entries):
            raise ValueError("A track ID was counted more than once")
        if any(event["metadata"]["reason"] != "entry" for event in entries):
            raise ValueError("Initial occupancy must not be called an entry")
        if any(not (directory / event["snapshot"]).is_file() for event in events):
            raise FileNotFoundError("An evidence snapshot is missing")
        database_uri = f"file:{video.with_suffix('.db').as_posix()}?mode=ro"
        connection = sqlite3.connect(database_uri, uri=True)
        try:
            persisted = connection.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        finally:
            connection.close()
        if persisted != len(events):
            raise ValueError("SQLite and event JSON differ")
        capture = cv2.VideoCapture(str(video))
        if not capture.isOpened():
            raise RuntimeError(f"Cannot open {video}")
        fps = capture.get(cv2.CAP_PROP_FPS)
        dimensions = (int(capture.get(cv2.CAP_PROP_FRAME_WIDTH)),
                      int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT)))
        decoded = 0
        sample = None
        while True:
            ok, frame = capture.read()
            if not ok:
                break
            decoded += 1
            if decoded == round(90 * fps):
                sample = frame
        capture.release()
        if decoded != payload["frames"] or dimensions != (1280, 720):
            raise ValueError("Decoded frames or resolution differ from the render manifest")
        duration = decoded / fps
        if not 179 <= duration <= 181 or sample is None:
            raise ValueError(f"Unexpected duration: {duration}")
        thumbnails.append(cv2.resize(sample, (768, 432)))
        record = {"camera_id": result["camera_id"], "decoded_frames": decoded,
                  "duration_seconds": round(duration, 3), "fps": fps,
                  "dimensions": list(dimensions), "bytes": video.stat().st_size,
                  "region_entries": len(entries), "persisted_events": persisted,
                  "snapshots_verified": len(events)}
        records.append(record)
        LOGGER.info("%s", json.dumps(record))
    preview = directory / "detection-preview.jpg"
    if not cv2.imwrite(str(preview), np.vstack([
        np.hstack(thumbnails[:2]), np.hstack(thumbnails[2:]),
    ])):
        raise OSError("Cannot save render preview")
    verification = directory / "verification.json"
    verification.write_text(json.dumps({"verified": True, "videos": records}, indent=2)
                            + "\n", encoding="utf-8")
    LOGGER.info("Verified all four outputs. Preview: %s", preview)


if __name__ == "__main__":
    console_logging()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    verify(parser.parse_args().directory.resolve())
