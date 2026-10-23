"""Record four live processed RTSP outputs, not four offline-rendered input videos."""

import argparse
import json
import logging
import subprocess
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

import cv2
import numpy as np

from app.config.loader import load_config
from app.telemetry import console_logging
from benchmarks.probe import RTSPProbe

LOGGER = logging.getLogger(__name__)


def tile(frame, label, stale=False):
    canvas = np.zeros((360, 640, 3), np.uint8)
    if frame is not None:
        height, width = frame.shape[:2]
        scale = min(640 / width, 360 / height)
        new_width, new_height = round(width * scale), round(height * scale)
        x, y = (640 - new_width) // 2, (360 - new_height) // 2
        canvas[y:y + new_height, x:x + new_width] = cv2.resize(frame, (new_width, new_height))
    cv2.rectangle(canvas, (0, 0), (640, 28), (0, 0, 0), -1)
    cv2.putText(canvas, label + (" | STALE" if stale else " | LIVE"), (8, 20),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 80, 255) if stale else (255, 255, 255),
                1, cv2.LINE_AA)
    return canvas


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, help="Generated config of the running service")
    parser.add_argument("--ffmpeg", required=True)
    parser.add_argument("--seconds", type=int, default=30)
    parser.add_argument("--fps", type=int, default=5)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not 10 <= args.seconds <= 180 or not 5 <= args.fps <= 15:
        parser.error("Use seconds 10..180 and recorder FPS 5..15")
    config = load_config(args.config)
    cameras = [camera for camera in config.cameras if camera.enabled]
    if len(cameras) != 4 or not config.streaming.enabled:
        parser.error("Exactly four enabled streaming cameras required")
    output = args.output.resolve()
    if output.exists() or output.with_suffix(".json").exists():
        raise FileExistsError("Choose a new demo output; existing files are preserved")
    output.parent.mkdir(parents=True, exist_ok=True)
    console_logging()
    cv2.setNumThreads(1)
    probes = []
    process = None
    frames = 0
    started = None
    temporary = tempfile.TemporaryDirectory(prefix="live-demo-", dir=output.parent)
    recording_frames = []
    try:
        for camera in cameras:
            probes.append(RTSPProbe(config.streaming.rtsp_server.rstrip("/")
                                    + "/" + camera.output_path, ffmpeg=args.ffmpeg,
                                    measure_latency=False))
        deadline = time.monotonic() + 30
        while not all(probe.last_frame is not None for probe in probes):
            if time.monotonic() > deadline:
                raise RuntimeError("Not all four RTSP outputs decoded: "
                                   + str([p.last_error for p in probes]))
            time.sleep(0.1)
        started = time.monotonic()
        started_wall = time.time()
        due = started
        while time.monotonic() - started < args.seconds:
            time.sleep(max(0, due - time.monotonic()))
            sampled_at = time.monotonic() - started
            if sampled_at >= args.seconds:
                break
            tiles = []
            for camera, probe in zip(cameras, probes, strict=True):
                with probe.lock:
                    frame = probe.last_frame
                    received = probe.samples[-1][0] if probe.samples else 0
                tiles.append(tile(frame, camera.id, time.monotonic() - received > 2))
            mosaic = np.vstack([np.hstack(tiles[:2]), np.hstack(tiles[2:])])
            header = np.zeros((40, 1280, 3), np.uint8)
            text = "LIVE RTSP OUTPUTS | Tran Danh Thien | " + datetime.now().strftime("%H:%M:%S")
            cv2.putText(header, text, (12, 27), cv2.FONT_HERSHEY_SIMPLEX,
                        0.65, (255, 255, 255), 1, cv2.LINE_AA)
            image_path = Path(temporary.name) / f"frame-{frames:05}.jpg"
            if not cv2.imwrite(str(image_path), np.vstack([header, mosaic])):
                raise OSError("Cannot save live sample")
            recording_frames.append((image_path, sampled_at))
            frames += 1
            # No catch-up burst: duration will come from actual sample timestamps.
            due = max(due + 1 / args.fps, time.monotonic())
        end = time.monotonic()
        concat = Path(temporary.name) / "frames.txt"
        lines = []
        for index, (image_path, sampled_at) in enumerate(recording_frames):
            following = (recording_frames[index + 1][1] if index + 1 < frames else args.seconds)
            lines.extend([f"file '{image_path.name}'",
                          f"duration {max(0.001, following - sampled_at)}"])
        lines.append(f"file '{recording_frames[-1][0].name}'")
        concat.write_text("\n".join(lines), encoding="utf-8")
        # Close clients before offline encoding; sampling time remains real wall time.
        for probe in probes:
            probe.close()
        process = subprocess.Popen([
            args.ffmpeg, "-v", "error", "-nostdin", "-n", "-f", "concat", "-safe", "0",
            "-filter_threads", "1", "-filter_complex_threads", "1",
            "-i", str(concat), "-an", "-c:v", "libx264", "-threads", "1",
            "-fps_mode", "vfr", "-preset", "fast", "-crf", "22", "-pix_fmt", "yuv420p",
            "-t", str(args.seconds), "-movflags", "+faststart", str(output),
        ])
        if process.wait(timeout=120) != 0:
            raise RuntimeError("Demo encoder failed")
        metadata = {
            "created_at": datetime.now(timezone.utc).isoformat(), "frames": frames,
            "recording_started_at": datetime.fromtimestamp(started_wall, timezone.utc).isoformat(),
            "recording_ended_at": datetime.fromtimestamp(
                started_wall + end - started, timezone.utc).isoformat(),
            "sample_timestamps_seconds": [round(value, 4) for _, value in recording_frames],
            "recorder_target_fps": args.fps, "video_seconds": args.seconds,
            "timing": "VFR with per-sample wall-clock durations, not accelerated playback",
            "wall_seconds": end - started, "camera_ids": [c.id for c in cameras],
            "source": "Four live processed RTSP outputs decoded concurrently",
            "not_a_benchmark": True,
            "note": "Recorder FPS may repeat latest frames. Not proof of inference FPS/latency.",
            "probes": [probe.report(started, end) for probe in probes],
        }
        output.with_suffix(".json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
        cv2.imwrite(str(output.with_suffix(".jpg")), np.vstack([header, mosaic]))
        LOGGER.info("Recorded %d live-client frames: %s", frames, output)
    finally:
        if process:
            if process.poll() is None:
                process.kill()
            process.wait(timeout=5)
        for probe in probes:
            probe.close()
        temporary.cleanup()


if __name__ == "__main__":
    main()
