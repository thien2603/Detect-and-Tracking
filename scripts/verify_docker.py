"""Smoke-test a running Compose project with real API, events and RTSP decoding."""

import argparse
import json
import logging
import re
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import URLError
from urllib.parse import quote, urlencode
from urllib.request import ProxyHandler, Request, build_opener

LOGGER = logging.getLogger(__name__)


def command(arguments, timeout=30):
    result = subprocess.run(arguments, capture_output=True, text=True, timeout=timeout)
    if result.returncode:
        raise RuntimeError(f"{arguments[0]} failed: {result.stderr[-2000:]}")
    return result.stdout.strip()


def wait_for(function, timeout):
    deadline = time.monotonic() + timeout
    last_error = None
    while time.monotonic() < deadline:
        try:
            result = function()
            if result:
                return result
        except (URLError, TimeoutError, OSError) as exc:
            last_error = exc
        time.sleep(1)
    raise TimeoutError(f"Condition did not become ready in {timeout}s; last error={last_error}")


def decode_one(ffmpeg, uri):
    began = time.monotonic()
    result = subprocess.run([
        ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin",
        "-rtsp_transport", "tcp", "-threads", "1", "-i", uri,
        "-map", "0:v:0", "-frames:v", "1", "-an", "-threads", "1",
        "-progress", "pipe:1", "-nostats", "-f", "null", "-",
    ], capture_output=True, text=True, timeout=60)
    frames = [int(value) for value in re.findall(r"^frame=(\d+)", result.stdout, re.M)]
    if result.returncode or not frames or max(frames) < 1:
        raise RuntimeError(f"Could not decode {uri}: {result.stderr[-1500:]}")
    return {"uri": uri, "decoded_frames": max(frames),
            "elapsed_seconds": round(time.monotonic() - began, 3)}


def verify(args, report):
    compose = ["docker", "compose"]
    if args.project:
        compose += ["-p", args.project]
    container = command([*compose, "ps", "-q", "app"])
    if not container or "\n" in container:
        raise RuntimeError("Expected exactly one running app container")
    since = command(["docker", "inspect", "--format", "{{.State.StartedAt}}", container])
    report.update(app_container=container, app_started_at=since)
    opener = build_opener(ProxyHandler({}))

    def request(path, data=None):
        payload = None if data is None else json.dumps(data).encode()
        query = Request(args.api.rstrip("/") + path, data=payload,
                        headers={"Content-Type": "application/json"},
                        method="GET" if data is None else "PUT")
        with opener.open(query, timeout=10) as response:
            return response.read()

    def get(path):
        return json.loads(request(path))

    report["health"] = wait_for(lambda: get("/health"), args.timeout)
    assert report["health"]["status"] == "ok"

    def ready_cameras():
        cameras = get("/api/v1/cameras")
        if len(cameras) != 4:
            raise AssertionError(f"Expected 4 cameras, got {len(cameras)}")
        return cameras if all(c["enabled"] and c["processed_frames"] > 0
                              and c["output_frames"] > 0 for c in cameras) else None

    cameras = wait_for(ready_cameras, args.timeout)
    report["cameras_before_toggle"] = cameras
    report["jpeg_bytes"] = {}
    for camera in cameras:
        jpeg = request(f"/api/v1/cameras/{quote(camera['id'])}/frame.jpg")
        assert jpeg.startswith(b"\xff\xd8"), "Invalid camera JPEG"
        report["jpeg_bytes"][camera["id"]] = len(jpeg)
    LOGGER.info("Four cameras have inference, published frames and valid JPEGs")

    with ThreadPoolExecutor(max_workers=2) as executor:
        report["rtsp_decodes"] = list(executor.map(
            lambda camera: decode_one(
                args.ffmpeg,
                args.rtsp.rstrip("/") + "/" + args.paths[camera["id"]],
            ), cameras))
    LOGGER.info("Decoded all four RTSP outputs through the host port")

    events_path = "/api/v1/events?" + urlencode({"start": since, "limit": 1000})
    events = wait_for(lambda: get(events_path), args.timeout)
    assert all(event["camera_id"] in {c["id"] for c in cameras} for event in events)
    report["events_since_start"] = len(events)
    report["event_types"] = sorted({event["event_type"] for event in events})
    event = events[0]
    filtered = get("/api/v1/events?" + urlencode({
        "camera_id": event["camera_id"], "start": since,
        "end": datetime.now(timezone.utc).isoformat(), "limit": 1000,
    }))
    assert filtered and all(item["camera_id"] == event["camera_id"] for item in filtered)
    snapshot = request(f"/api/v1/events/{quote(event['id'])}/snapshot")
    assert snapshot.startswith(b"\xff\xd8"), "Invalid event snapshot"
    report["snapshot"] = {"event_id": event["id"], "bytes": len(snapshot)}
    report["event_filter_passed"] = True

    selected = cameras[0]
    identifier = selected["id"]
    path = f"/api/v1/cameras/{quote(identifier)}/enabled"
    try:
        stopped = json.loads(request(path, {"enabled": False}))
        assert stopped["enabled"] is False
        others = [c for c in get("/api/v1/cameras") if c["id"] != identifier]

        def others_advanced():
            current = {c["id"]: c for c in get("/api/v1/cameras")}
            return all(current[c["id"]]["processed_frames"] > c["processed_frames"]
                       for c in others)

        wait_for(others_advanced, args.timeout)
        report["other_cameras_continued_while_disabled"] = True
    finally:
        resumed = json.loads(request(path, {"enabled": True}))
    assert resumed["enabled"] and resumed["session_id"] != selected["session_id"]
    report["cameras_after_toggle"] = wait_for(ready_cameras, args.timeout)
    report["hot_toggle_passed"] = True
    report["health_after"] = get("/health")
    assert report["health_after"]["evidence_failed"] == 0
    LOGGER.info("Fresh events, snapshot, filter and camera hot-toggle passed")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api", default="http://127.0.0.1:8000")
    parser.add_argument("--rtsp", default="rtsp://127.0.0.1:8554/processed")
    parser.add_argument("--ffmpeg", required=True)
    parser.add_argument("--project")
    parser.add_argument("--timeout", type=int, default=240)
    parser.add_argument("--config", type=Path, default=Path("configs/submission-four.yaml"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError("Choose a new verification output")
    import yaml

    cameras = yaml.safe_load(args.config.read_text(encoding="utf-8"))["cameras"]
    args.paths = {camera["id"]: camera["output_path"] for camera in cameras}
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    report = {"started_at": datetime.now(timezone.utc).isoformat(),
              "scope": "Docker CPU functionality smoke test; not a GPU FPS benchmark",
              "passed": False}
    try:
        verify(args, report)
        report["passed"] = True
    except Exception as exc:
        report["error"] = f"{type(exc).__name__}: {exc}"
        LOGGER.exception("Docker smoke test failed")
    finally:
        report["finished_at"] = datetime.now(timezone.utc).isoformat()
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    raise SystemExit(0 if report["passed"] else 1)


if __name__ == "__main__":
    main()
