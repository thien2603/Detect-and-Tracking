"""Prepare three-minute clips from four public Bellevue traffic cameras."""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import logging
import re
import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from app.telemetry import console_logging

LOGGER = logging.getLogger(__name__)
CAMERAS = (
    ("cam01-eastgate", "1ZVFa8uVnSIhfcX7pMmobko6Eo0nGiYOP"),
    ("cam02-newport", "1IlFGcM9SzNc6ArR8AozE2afem1J3GlQ0"),
    ("cam03-se38th", "1IbY5V26iEu2dh8AkAdSNLL_aKpqmJk9W"),
    ("cam04-ne8th", "11zD3GffsvHar97p5Zofa7Pc8z0JRrC6k"),
)
SOURCE = "https://github.com/City-of-Bellevue/TrafficVideoDataset"


def public_download_url(file_id: str) -> str:
    """Follow the public large-file download confirmation, without credentials."""
    url = f"https://drive.usercontent.google.com/uc?id={file_id}&export=download"
    request = Request(url, headers={"Range": "bytes=0-65535"})
    with urlopen(request, timeout=30) as response:
        if "text/html" not in response.headers.get("Content-Type", ""):
            return response.url
        page = response.read(65536).decode("utf-8")
    form = re.search(r'<form[^>]+action="([^"]+)"', page)
    fields = dict(
        re.findall(r'<input[^>]+name="([^"]+)"[^>]+value="([^"]*)"', page)
    )
    if not form or fields.get("id") != file_id:
        raise RuntimeError("Public download unavailable; no login or access bypass attempted")
    action = html.unescape(form[1])
    if not action.startswith("https://drive.usercontent.google.com/"):
        raise RuntimeError("Unexpected download host")
    return action + "?" + urlencode(fields)


def inspect_clip(ffmpeg: str, path: Path, seconds: int) -> dict:
    """Decode every frame to check that the resulting MP4 is complete."""
    check = subprocess.run(
        [ffmpeg, "-hide_banner", "-xerror", "-threads", "1", "-i", str(path), "-map", "0:v:0",
         "-an", "-f", "null", "-", "-progress", "pipe:1", "-nostats"],
        capture_output=True, text=True, timeout=300,
    )
    if check.returncode:
        raise RuntimeError(check.stderr[-4000:])
    duration = re.search(r"Duration: (\d+):(\d+):(\d+\.\d+)", check.stderr)
    frames = re.findall(r"^frame=(\d+)$", check.stdout, re.MULTILINE)
    video = re.search(r"Video:.*", check.stderr)
    dimensions = re.search(r"\b(\d{3,5})x(\d{3,5})\b", video[0] if video else "")
    fps = re.search(r"\b([\d.]+) fps", video[0] if video else "")
    if not duration or not frames:
        raise RuntimeError("Missing duration or decoded frame count")
    actual = int(duration[1]) * 3600 + int(duration[2]) * 60 + float(duration[3])
    if abs(actual - seconds) > 0.2 or int(frames[-1]) == 0:
        raise RuntimeError(f"Unexpected clip duration/frame count: {actual}, {frames[-1]}")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return {
        "duration_seconds": actual,
        "decoded_frames": int(frames[-1]),
        "width": int(dimensions[1]) if dimensions else None,
        "height": int(dimensions[2]) if dimensions else None,
        "fps": float(fps[1]) if fps else None,
        "bytes": path.stat().st_size,
        "sha256": digest.hexdigest(),
    }


def prepare(camera: tuple[str, str], args: argparse.Namespace) -> dict:
    name, file_id = camera
    output = args.output / f"{name}-{args.seconds}s.mp4"
    if output.exists():
        raise FileExistsError(f"Refusing to overwrite existing file: {output}")
    LOGGER.info("[%s] Resolving public download...", name)
    url = public_download_url(file_id)
    with tempfile.TemporaryDirectory(prefix=f".{name}-", dir=args.output) as temporary:
        partial = Path(temporary) / output.name
        command = [
            args.ffmpeg, "-hide_banner", "-loglevel", "warning", "-nostdin", "-n",
            "-rw_timeout", "30000000", "-i", url,
            "-t", str(args.seconds), "-map", "0:v:0", "-an", "-c:v", "copy",
            "-movflags", "+faststart", str(partial),
        ]
        result = subprocess.run(command, capture_output=True, text=True, timeout=600)
        if result.returncode:
            # Download confirmation URLs may contain ephemeral tokens; keep them out of logs.
            raise RuntimeError(
                f"{name}: FFmpeg could not prepare public video (exit {result.returncode})"
            )
        LOGGER.info("[%s] Download complete; validating all frames...", name)
        metadata = inspect_clip(args.ffmpeg, partial, args.seconds)
        partial.rename(output)
    metadata.update({
        "camera": name,
        "file": output.name,
        "source_url": f"https://drive.google.com/file/d/{file_id}/view",
        "source_dataset": SOURCE,
        "start_seconds": 0,
        "preparation": "First three minutes; original video stream copied without resizing, "
                       "FPS conversion, looping or detection overlays. Audio omitted.",
        "note": "Camera orientation has not been checked for the full clip. "
                "See publisher terms for research use.",
    })
    LOGGER.info("[%s] OK: %ss, %s FPS, %d frames, %.1f MB", name,
                metadata["duration_seconds"], metadata["fps"], metadata["decoded_frames"],
                metadata["bytes"] / 1e6)
    return metadata


def main() -> None:
    console_logging()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ffmpeg", required=True)
    parser.add_argument("--seconds", type=int, default=180, choices=range(120, 181))
    parser.add_argument("--output", type=Path, default=Path(__file__).resolve().parents[1]
                        / "data" / "videos" / "bellevue")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    manifest = args.output / "sources.json"
    if manifest.exists():
        raise FileExistsError(f"Refusing to overwrite existing manifest: {manifest}")
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda camera: prepare(camera, args), CAMERAS))
    manifest.write_text(json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    LOGGER.info("Prepared %d videos in %s", len(results), args.output)


if __name__ == "__main__":
    main()
