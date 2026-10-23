"""Download the public VietNamNet expressway clip; preserve the source watermark."""

from __future__ import annotations

import hashlib
import json
import logging
import re
import subprocess
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urljoin, urlsplit
from urllib.request import Request, urlopen

from app.telemetry import console_logging

LOGGER = logging.getLogger(__name__)
ARTICLE = (
    "https://vietnamnet.vn/tac-tren-cao-toc-ngay-le-nhieu-o-to-di-vao-lan-khan-cap-"
    "chen-duong-xe-cap-cuu-2276071.html"
)
OUTPUT = Path("data/videos/vietnam-expressway/highway-126s.mp4")


def fetch(url):
    last_error = None
    for attempt in range(3):
        try:
            request = Request(url, headers={"User-Agent": "VehicleAnalytics/0.2"})
            with urlopen(request, timeout=30) as response:
                return response.read()
        except OSError as exc:
            last_error = exc
            if attempt < 2:
                time.sleep(1 + attempt)
    raise RuntimeError(f"Cannot fetch public source {url}: {last_error}")


def prepare(output=OUTPUT):
    output = Path(output)
    article = fetch(ARTICLE).decode("utf-8")
    match = re.search(r'<iframe[^>]+src="(https://embed\.vietnamnet\.vn/[^\"]+)"', article)
    if not match:
        raise RuntimeError("Publisher player changed. Inspect the article before downloading.")
    embed = match[1].replace("&amp;", "&")
    player = fetch(embed).decode("utf-8")
    hls = re.search(r"var hls\s*=\s*'([^']+)'", player)
    if not hls:
        raise RuntimeError("Public HLS manifest missing")
    master_url = hls[1]
    master = fetch(master_url).decode("utf-8")
    lines = [line.strip() for line in master.splitlines()]
    if "#EXT-X-STREAM-INF" in master:
        variants = [
            (lines[i], lines[i + 1])
            for i in range(len(lines) - 1)
            if lines[i].startswith("#EXT-X-STREAM-INF")
        ]
        chosen = next((v for v in variants if "480" in v[0]), variants[0])
        variant = urljoin(master_url, chosen[1])
        playlist = fetch(variant).decode("utf-8")
    else:
        variant, playlist = master_url, master
    if "#EXT-X-KEY" in playlist or "#EXT-X-ENDLIST" not in playlist:
        raise RuntimeError("Only unencrypted, complete public VOD playlists are supported")
    parts = [
        line.strip() for line in playlist.splitlines() if line.strip() and not line.startswith("#")
    ]
    if not parts or len(parts) > 1000:
        raise RuntimeError("Unexpected publisher playlist")
    urls = [urljoin(variant, part) for part in parts]
    if any(urlsplit(u).scheme != "https" for u in urls):
        raise RuntimeError("Only HTTPS media URLs are accepted")
    output.parent.mkdir(parents=True, exist_ok=True)
    partial = output.with_name(output.stem + ".partial.mp4")
    with tempfile.TemporaryDirectory(prefix="expressway-") as directory:
        root = Path(directory)

        def download(item):
            index, uri = item
            (root / f"{index:04}.ts").write_bytes(fetch(uri))

        with ThreadPoolExecutor(max_workers=6) as executor:
            list(executor.map(download, enumerate(urls)))
        concat = root / "segments.txt"
        concat.write_text("".join(f"file '{i:04}.ts'\n" for i in range(len(parts))))
        # The inspected publisher clip has 29.97 FPS. Verify this before repairing gaps.
        probe = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream=r_frame_rate",
                "-of",
                "json",
                str(root / "0000.ts"),
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        rate = json.loads(probe.stdout)["streams"][0]["r_frame_rate"]
        a, b = map(int, rate.split("/"))
        if abs(a / b - 30000 / 1001) > 0.05:
            raise RuntimeError(f"Source FPS changed ({rate}); recalibrate before preparing video")
        subprocess.run(
            [
                "ffmpeg",
                "-v",
                "error",
                "-y",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(concat),
                "-map",
                "0:v:0",
                "-an",
                "-vf",
                "setpts=N*1001/(30000*TB),scale=640:360,fps=10",
                "-c:v",
                "libx264",
                "-threads",
                "1",
                "-preset",
                "fast",
                "-crf",
                "22",
                "-pix_fmt",
                "yuv420p",
                "-movflags",
                "+faststart",
                str(partial),
            ],
            check=True,
        )
    probe = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "json",
            str(partial),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    duration = float(json.loads(probe.stdout)["format"]["duration"])
    if not 120 <= duration <= 180:
        raise RuntimeError(f"Expected 2–3 minutes, got {duration}s. Source may have changed.")
    partial.replace(output)
    metadata = {
        "publisher": "VietNamNet",
        "article_url": ARTICLE,
        "embed_url": embed,
        "hls_variant": variant,
        "duration_seconds": duration,
        "sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
        "locations_according_to_publisher": [
            "Cao tốc Hải Phòng–Hạ Long, cầu Bạch Đằng, 28/4/2024",
            "Cao tốc Hải Phòng–Hà Nội, 30/4/2024",
        ],
        "note": "Publisher footage, not an open dataset. Moving camera; includes trucks and buses.",
        "preparation": "Repair HLS timestamp gaps from original frame index at 30000/1001 FPS; "
        "sample 10 FPS, resize 640x360. No looping or slow motion.",
    }
    output.with_suffix(".source.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    LOGGER.info("Prepared %s: %.1fs", output, duration)


if __name__ == "__main__":
    console_logging()
    prepare()
