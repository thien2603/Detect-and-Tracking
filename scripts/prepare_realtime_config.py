"""Create portable local/RTSP/Docker variants from approved camera geometry."""

import argparse
import copy
from pathlib import Path

import yaml

from app.config.loader import load_config
from app.config.schemas import AppConfig
from app.telemetry import console_logging

ROOT = Path(__file__).resolve().parents[1]


def build_config(base, count=None, *, rtsp_server=None, batch_size=4, output=None, device="0"):
    data = base.model_dump(mode="json")
    original = data["cameras"]
    count = len(original) if count is None else count
    if count < 1:
        raise ValueError("Camera count must be positive")
    cameras = []
    for index in range(count):
        camera = copy.deepcopy(original[index % len(original)])
        if index >= len(original):
            camera["id"] = f"stress_{index + 1:02}_{camera['id']}"
            camera["output_path"] = f"stress/{index + 1:02}"
        camera["source"]["loop"] = True
        if rtsp_server:
            camera["source"] = {
                "type": "rtsp", "uri": rtsp_server.rstrip("/") + "/source/" + camera["id"],
                "reconnect_seconds": 0.5,
            }
        cameras.append(camera)
    data["cameras"] = cameras
    data["model"].update(device=device, batch_size=batch_size,
                         batch_wait_ms=base.model.batch_wait_ms if batch_size > 1 else 0)
    data["streaming"].update(enabled=True, timestamp_overlay=True,
                              output_fps=base.streaming.output_fps
                              if base.model.async_inference else 12)
    if rtsp_server:
        data["streaming"]["rtsp_server"] = rtsp_server.rstrip("/") + "/processed"
    if output:
        output = Path(output).resolve()
        data["database"] = {"path": str(output / "events.db"),
                            "snapshot_dir": str(output / "snapshots")}
        data["logging"]["file"] = str(output / "service.log")
    return data


def save_config(data, path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", type=Path, default=ROOT / "configs/bellevue.yaml")
    parser.add_argument("--output", type=Path, default=ROOT / "configs/bellevue-realtime.yaml")
    parser.add_argument("--rtsp-server", default="rtsp://127.0.0.1:8554")
    parser.add_argument("--count", type=int, help="Default: every camera declared in the YAML")
    parser.add_argument("--device", default="0")
    parser.add_argument("--portable", action="store_true",
                        help="Keep relative model/data paths, for Docker")
    args = parser.parse_args()
    console_logging()
    base = (AppConfig.model_validate(yaml.safe_load(args.base.read_text())) if args.portable
            else load_config(args.base))
    config = build_config(base, args.count, rtsp_server=args.rtsp_server,
                          device=args.device)
    save_config(config, args.output)


if __name__ == "__main__":
    main()
