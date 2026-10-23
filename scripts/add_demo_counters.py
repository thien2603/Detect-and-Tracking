"""Display persisted event totals at their recorded wall times, preserving the live VFR footage."""

import argparse
import json
import logging
import sqlite3
import subprocess
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

import cv2


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--video", type=Path, required=True)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--ffmpeg", required=True)
    args = parser.parse_args()
    if args.output.exists() or args.output.with_suffix(".json").exists():
        raise FileExistsError("Refusing to overwrite existing demo")
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    metadata = json.loads(args.video.with_suffix(".json").read_text())
    started = datetime.fromisoformat(metadata["recording_started_at"])
    with sqlite3.connect(args.database.resolve().as_uri() + "?mode=ro", uri=True) as database:
        events = [json.loads(row[0]) for row in database.execute(
            "SELECT payload FROM events ORDER BY occurred_at ASC")]
    totals = {camera: {"negative_to_positive": 0, "positive_to_negative": 0,
                       "region_entries": 0, "alerts": 0} for camera in metadata["camera_ids"]}
    event_index, history, images = 0, [], []
    capture = cv2.VideoCapture(str(args.video), cv2.CAP_FFMPEG, [cv2.CAP_PROP_N_THREADS, 1])
    cv2.setNumThreads(1)
    try:
        with tempfile.TemporaryDirectory(prefix="demo-counters-", dir=args.output.parent) as folder:
            for index, seconds in enumerate(metadata["sample_timestamps_seconds"]):
                ok, frame = capture.read()
                if not ok:
                    raise RuntimeError("Demo frame count differs from its sampling metadata")
                wall = started + timedelta(seconds=seconds)
                while (event_index < len(events)
                       and datetime.fromisoformat(events[event_index]["occurred_at"]) <= wall):
                    event = events[event_index]
                    counts = totals[event["camera_id"]]
                    if event["event_type"] == "line_crossing":
                        counts[event["metadata"]["direction"]] += 1
                    elif event["event_type"] == "region_entry":
                        counts["region_entries"] += 1
                    elif event["event_type"] == "intrusion":
                        counts["alerts"] += 1
                    event_index += 1
                for number, camera in enumerate(metadata["camera_ids"]):
                    x, y = (number % 2) * 640, 40 + (number // 2) * 360
                    counts = totals[camera]
                    label = (f"DB A>B {counts['negative_to_positive']} B>A "
                             f"{counts['positive_to_negative']} ENT {counts['region_entries']} "
                             f"ZONE {counts['alerts']}")
                    # Retain the original camera ID and LIVE/STALE status on the left.
                    cv2.rectangle(frame, (x + 265, y), (x + 639, y + 27), (0, 0, 0), -1)
                    cv2.putText(frame, label, (x + 270, y + 20), cv2.FONT_HERSHEY_SIMPLEX,
                                0.42, (80, 230, 230), 1, cv2.LINE_AA)
                image = Path(folder) / f"frame-{index:05}.jpg"
                if not cv2.imwrite(str(image), frame):
                    raise OSError("Cannot save counter overlay")
                images.append(image)
                history.append({"seconds": seconds,
                                "cameras": {key: dict(value) for key, value in totals.items()}})
            lines = []
            times = metadata["sample_timestamps_seconds"]
            for index, image in enumerate(images):
                following = (times[index + 1] if index + 1 < len(times)
                             else metadata["video_seconds"])
                lines.extend([f"file '{image.name}'",
                              f"duration {max(0.001, following - times[index])}"])
            lines.append(f"file '{images[-1].name}'")
            concat = Path(folder) / "frames.txt"
            concat.write_text("\n".join(lines), encoding="utf-8")
            subprocess.run([
                args.ffmpeg, "-v", "error", "-nostdin", "-n", "-f", "concat", "-safe", "0",
                "-filter_threads", "1", "-i", str(concat), "-an", "-c:v", "libx264",
                "-threads", "1", "-fps_mode", "vfr", "-preset", "fast", "-crf", "22",
                "-pix_fmt", "yuv420p", "-t", str(metadata["video_seconds"]),
                "-movflags", "+faststart", str(args.output),
            ], check=True, timeout=120)
        metadata["counter_overlay"] = (
            "Cumulative persisted DB event counts as of each wall-clock sample, "
            "not frame-synchronized camera exposure or unique physical-object ground truth")
        metadata["counter_history"] = history
        args.output.with_suffix(".json").write_text(json.dumps(metadata, indent=2),
                                                   encoding="utf-8")
        cv2.imwrite(str(args.output.with_suffix(".jpg")), frame)
        logging.info("Added visible timestamp-aligned DB counters without replacing live footage")
    finally:
        capture.release()


if __name__ == "__main__":
    main()
