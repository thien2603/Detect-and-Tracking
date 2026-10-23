"""Prepare a local Crosswalk clip without downloading or modifying the original AVI."""

import argparse
import json
import logging
import subprocess
import tempfile
from pathlib import Path

from app.telemetry import console_logging
from scripts.prepare_bellevue import inspect_clip

LOGGER = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--ffmpeg", required=True)
    parser.add_argument("--seconds", type=int, choices=range(120, 181), default=180)
    parser.add_argument("--output", type=Path,
                        default=Path("data/videos/pedestrians/crosswalk-video002-180s.mp4"))
    args = parser.parse_args()
    console_logging()
    if not args.source.is_file():
        parser.error("Source AVI not found")
    output = args.output.resolve()
    if output.exists() or output.with_suffix(".source.json").exists():
        raise FileExistsError("Choose a new output path; existing files are preserved")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="crosswalk-", dir=output.parent) as temporary:
        partial = Path(temporary) / output.name
        LOGGER.info("Encoding %ds; preserving original dimensions and frame rate", args.seconds)
        subprocess.run([
            args.ffmpeg, "-v", "error", "-nostdin", "-n", "-threads", "1",
            "-filter_threads", "1",
            "-i", str(args.source), "-t", str(args.seconds), "-map", "0:v:0", "-an",
            "-c:v", "libx264", "-threads", "2", "-preset", "veryfast", "-crf", "23",
            "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(partial),
        ], check=True, timeout=600)
        metadata = inspect_clip(args.ffmpeg, partial, args.seconds)
        partial.rename(output)
    metadata.update({
        "source_local": str(args.source.resolve()), "file": output.name, "start_seconds": 0,
        "dataset": "Crosswalk Bangkok", "original_file": "video_002.avi",
        "dataset_url": "https://figshare.com/articles/dataset/29983897",
        "source_file_url": "https://ndownloader.figshare.com/files/57418396",
        "preparation": "First 180 seconds, H.264 transcode; no resize, loop or FPS conversion",
        "license_note": "Verify Figshare and dataset README license terms before redistribution",
    })
    output.with_suffix(".source.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    LOGGER.info("Prepared and decoded all %d frames: %s", metadata["decoded_frames"], output)


if __name__ == "__main__":
    main()
