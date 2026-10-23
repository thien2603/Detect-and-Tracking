"""Create a portable full-source ZIP, including current model/video/results when available."""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import zipfile
from pathlib import Path

from app.telemetry import console_logging

LOGGER = logging.getLogger(__name__)

def main():
    console_logging()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="../Tracking_Detection_full_source.zip")
    args = parser.parse_args()
    root = Path(__file__).resolve().parent.parent
    output = Path(args.output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    files = []
    for folder in ("app", "configs", "scripts", "tests", "benchmarks", "infrastructure", "docs"):
        files.extend(
            p for p in (root / folder).rglob("*") if p.is_file() and "__pycache__" not in p.parts
        )
    for name in (
        "README.md",
        "pyproject.toml",
        "requirements-tested.txt",
        "Dockerfile",
        "docker-compose.yml",
        "Makefile",
        ".gitignore",
        ".dockerignore",
        ".env.example",
    ):
        path = root / name
        if path.is_file():
            files.append(path)
    files.extend(
        p for folder in ("models", "data", "logs") for p in (root / folder).rglob(".gitkeep")
    )
    for name in (
        "models/yolo11n.pt",
        "data/videos/vietnam-expressway/highway-126s.mp4",
        "data/videos/vietnam-expressway/highway-126s.source.json",
        "data/vietnam-expressway-tracking.mp4",
        "data/vietnam-expressway-tracking.events.json",
        "data/vietnam-expressway-tracking.db",
    ):
        path = root / name
        if path.is_file():
            files.append(path)
    files.extend((root / "data/vietnam-expressway-tracking-snapshots").glob("*.jpg"))
    manifest = {}
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(set(files)):
            name = path.relative_to(root).as_posix()
            archive.write(path, name)
            manifest[name] = hashlib.sha256(path.read_bytes()).hexdigest()
        archive.writestr("MANIFEST.sha256.json", json.dumps(manifest, indent=2))
    with zipfile.ZipFile(output) as archive:
        bad = archive.testzip()
        if bad:
            raise RuntimeError(f"ZIP verification failed: {bad}")
        required = {"app/main.py", "scripts/render_video.py", "README.md", "pyproject.toml"}
        if not required.issubset(archive.namelist()):
            raise RuntimeError("Source files missing")
    LOGGER.info("Saved %s: %d files, %.2f MiB", output, len(manifest),
                output.stat().st_size / 1048576)


if __name__ == "__main__":
    main()
