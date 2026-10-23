"""Render a complete file video and save event JSON, SQLite and snapshots."""

from __future__ import annotations

import argparse
import json
import logging
import shutil
import subprocess
from pathlib import Path

import cv2

from app.config.loader import load_config
from app.events.repository import EventRepository
from app.inference.detector import YOLODetector
from app.pipeline import AnalyticsPipeline
from app.telemetry import console_logging

LOGGER = logging.getLogger(__name__)


def render(config, camera, output, detector, fps=10, max_seconds=None):
    if camera.source.type != "file":
        raise ValueError("Offline renderer requires a file camera")
    if not shutil.which(config.streaming.ffmpeg_bin):
        raise RuntimeError("FFmpeg not found. Install FFmpeg and add it to PATH.")
    output = Path(output).resolve()
    if output == Path(camera.source.uri).resolve():
        raise ValueError("Output must differ from the input video")
    output.parent.mkdir(parents=True, exist_ok=True)
    capture = cv2.VideoCapture(str(camera.source.uri))
    if not capture.isOpened():
        raise RuntimeError(f"Cannot open {camera.source.uri}")
    source_fps = capture.get(cv2.CAP_PROP_FPS)
    width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
    if source_fps <= 0 or width % 2 or height % 2:
        capture.release()
        raise ValueError("Source must have a valid FPS and even width/height")
    fps = min(float(fps), source_fps)
    pipeline = AnalyticsPipeline(camera)
    snapshots = output.parent / (output.stem + "-snapshots")
    repository = EventRepository(output.with_suffix(".db"), snapshots)
    partial = output.with_name(output.stem + ".partial.mp4")
    process = None
    events, input_number, output_number = [], 0, 0

    def write_batch(batch):
        nonlocal output_number
        detections_batch = detector.detect_batch([frame for frame, _ in batch])
        if len(detections_batch) != len(batch):
            raise RuntimeError("Detector returned an invalid batch length")
        for (frame, seconds), detections in zip(batch, detections_batch, strict=True):
            canvas, candidates, _ = pipeline.process(
                frame, detections, seconds, fps, video_seconds=round(seconds, 4)
            )
            for event in candidates:
                repository.save(event, canvas)
                record = event.to_dict()
                record["snapshot"] = str(Path(record["snapshot"]).relative_to(output.parent))
                events.append(record)
            process.stdin.write(canvas.tobytes())
            output_number += 1
            if output_number % max(1, round(fps * 30)) == 0:
                LOGGER.info("Rendered %.1fs; %d events", output_number / fps, len(events))

    try:
        process = subprocess.Popen(
            [
                config.streaming.ffmpeg_bin,
                "-y",
                "-v",
                "error",
                "-filter_threads",
                "1",
                "-f",
                "rawvideo",
                "-pix_fmt",
                "bgr24",
                "-s",
                f"{width}x{height}",
                "-r",
                str(fps),
                "-i",
                "-",
                "-an",
                "-c:v",
                "libx264",
                "-threads",
                "1",
                "-preset",
                "fast",
                "-crf",
                "23",
                "-pix_fmt",
                "yuv420p",
                "-movflags",
                "+faststart",
                str(partial),
            ],
            stdin=subprocess.PIPE,
        )
        pending = []
        while True:
            ok, frame = capture.read()
            if not ok:
                break
            seconds = input_number / source_fps
            input_number += 1
            if max_seconds is not None and seconds >= max_seconds:
                break
            if seconds + 1e-7 < (output_number + len(pending)) / fps:
                continue
            pending.append((frame, seconds))
            if len(pending) >= config.model.batch_size:
                write_batch(pending)
                pending = []
        if pending:
            write_batch(pending)
        process.stdin.close()
        return_code = process.wait(timeout=60)
        if return_code:
            raise RuntimeError(f"FFmpeg failed with exit code {return_code}")
        if not output_number:
            raise RuntimeError("Source contains no readable frames")
        partial.replace(output)
        payload = {
            "source": str(camera.source.uri),
            "camera_id": camera.id,
            "session_id": pipeline.session_id,
            "frames": output_number,
            "fps": fps,
            "duration_seconds": output_number / fps,
            "counts": pipeline.processor.counts,
            "note": "Geometric alerts, not legal findings. first_seen_inside is not a crossing.",
            "events": events,
        }
        output.with_suffix(".events.json").write_text(
            json.dumps(payload, indent=2), encoding="utf-8"
        )
        return payload
    finally:
        capture.release()
        if process:
            if process.poll() is None:
                process.kill()
                process.wait()
            if process.stdin and not process.stdin.closed:
                process.stdin.close()
        repository.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="configs/vietnam-expressway.yaml")
    parser.add_argument("--camera")
    parser.add_argument(
        "--zone-schedule", help="Override schedule path, relative to working directory"
    )
    parser.add_argument("--output", default="data/vietnam-expressway-tracking.mp4")
    parser.add_argument("--fps", type=float, default=10)
    parser.add_argument("--max-seconds", type=float)
    args = parser.parse_args()
    console_logging()
    if not 1 <= args.fps <= 60 or (args.max_seconds is not None and args.max_seconds <= 0):
        parser.error("FPS must be 1..60 and max-seconds must be positive")
    config = load_config(args.config)
    selected = [c for c in config.cameras if args.camera is None or c.id == args.camera]
    if not selected:
        parser.error("Unknown camera")
    camera = selected[0]
    if args.zone_schedule:
        camera.zone_schedule = str(Path(args.zone_schedule).resolve())
    result = render(
        config, camera, args.output, YOLODetector(config.model), args.fps, args.max_seconds
    )
    LOGGER.info("Saved %s: %.1fs, %d events", args.output,
                result["duration_seconds"], len(result["events"]))


if __name__ == "__main__":
    main()
