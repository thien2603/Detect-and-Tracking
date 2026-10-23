import json
import os
import shutil
import time
from datetime import datetime, timezone
from threading import Event

import cv2
import numpy as np
import pytest
import yaml
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.config.loader import ConfigError, load_config
from app.config.schemas import AppConfig, SourceConfig, ZoneConfig
from app.events.repository import EventRepository, EventWriter
from app.events.types import EventCandidate
from app.inference.scheduler import InferenceScheduler
from app.main import create_app
from app.pipeline import AnalyticsPipeline
from scripts.render_video import render
from tests.conftest import detection

UTC = timezone.utc


class FakeDetector:
    def detect_batch(self, frames):
        return [[detection(x=60, y=100)] for _ in frames]


def write_config(tmp_path, video, enabled=False):
    path = tmp_path / "project" / "configs" / "config.yaml"
    path.parent.mkdir(parents=True)
    path.write_text(
        yaml.safe_dump(
            {
                "model": {"classes": ["car"]},
                "database": {
                    "path": str(tmp_path / "events.db"),
                    "snapshot_dir": str(tmp_path / "snapshots"),
                },
                "logging": {"file": str(tmp_path / "app.log")},
                "cameras": [
                    {
                        "id": "test",
                        "enabled": enabled,
                        "source": {"type": "file", "uri": str(video)},
                        "output_path": "test",
                        "forbidden_zones": [
                            {"id": "zone", "points": [[40, 0], [100, 0], [100, 150], [40, 150]]}
                        ],
                    }
                ],
            }
        )
    )
    return path


def test_reject_duplicate_camera_ids(camera):
    with pytest.raises(ValidationError):
        AppConfig(cameras=[camera, camera])


def test_reject_bad_rtsp():
    with pytest.raises(ValidationError):
        SourceConfig(type="rtsp", uri="http://example.com/video")


def test_missing_input_has_actionable_error(tmp_path):
    path = write_config(tmp_path, tmp_path / "missing.mp4", enabled=True)
    with pytest.raises(ConfigError, match="Missing source"):
        load_config(path)


def test_pipeline_filters_before_events(camera):
    camera.detection_region = ZoneConfig(id="road", points=[(0, 0), (30, 0), (30, 100), (0, 100)])
    camera.forbidden_zones = [
        ZoneConfig(id="zone", points=[(40, 0), (100, 0), (100, 100), (40, 100)])
    ]
    pipeline = AnalyticsPipeline(camera)
    _, events, tracks = pipeline.process(np.zeros((240, 320, 3), np.uint8), [detection(x=60)], 0)
    assert events == [] and tracks == []


def test_repository_writer_drains_and_filters(tmp_path):
    repo = EventRepository(tmp_path / "events.db", tmp_path / "snapshots")
    writer = EventWriter(repo)
    event = EventCandidate("cam", "session", 1, "car", "intrusion", "zone")
    writer.submit(event, np.zeros((30, 30, 3), np.uint8))
    writer.close()
    assert repo.query("cam")[0]["track_id"] == 1
    assert not repo.query("other")
    assert repo.snapshot_for(event.id)
    assert not repo.query(start="2999-01-01T00:00:00+00:00")
    repo.close()


def test_scheduler_propagates_failure_and_recovers():
    class Detector:
        calls = 0

        def detect_batch(self, frames):
            self.calls += 1
            if self.calls == 1:
                raise ValueError("model failure")
            return [[] for _ in frames]

    scheduler = InferenceScheduler(Detector())
    try:
        with pytest.raises(ValueError, match="model failure"):
            scheduler.submit("a", None).result(timeout=2)
        assert scheduler.submit("b", None).result(timeout=2) == []
    finally:
        scheduler.close()


def test_scheduler_replaces_pending_and_rejects_after_close():
    started, release = Event(), Event()

    class Detector:
        def detect_batch(self, frames):
            started.set()
            assert release.wait(3)
            return [[] for _ in frames]

    scheduler = InferenceScheduler(Detector())
    try:
        first = scheduler.submit("busy", None)
        assert started.wait(2)
        replaced = scheduler.submit("waiting", None)
        last = scheduler.submit("waiting", None)
        assert replaced.cancelled()
        release.set()
        assert first.result(timeout=2) == []
        assert last.result(timeout=2) == []
    finally:
        release.set()
        scheduler.close()
    with pytest.raises(RuntimeError, match="stopped"):
        scheduler.submit("a", None).result()


def test_scheduler_invalid_batch_length():
    class Detector:
        def detect_batch(self, frames):
            return []

    scheduler = InferenceScheduler(Detector())
    try:
        with pytest.raises(RuntimeError, match="batch length"):
            scheduler.submit("a", None).result(timeout=2)
    finally:
        scheduler.close()


def test_api_validation_and_camera_enable(tmp_path, video):
    app = create_app(write_config(tmp_path, video), detector=FakeDetector())
    with TestClient(app) as client:
        assert client.get("/health").status_code == 200
        assert client.get("/api/v1/cameras").json()[0]["enabled"] is False
        assert (
            client.put("/api/v1/cameras/missing/enabled", json={"enabled": True}).status_code == 404
        )
        assert (
            client.put("/api/v1/cameras/test/enabled", json={"enabled": "false"}).status_code == 422
        )
        start = client.put("/api/v1/cameras/test/enabled", json={"enabled": True}).json()
        deadline = time.monotonic() + 5
        events = []
        while time.monotonic() < deadline:
            events = client.get("/api/v1/events").json()
            if events:
                break
            time.sleep(0.05)
        assert events and events[0]["metadata"]["reason"] == "first_seen_inside"
        assert client.get(f"/api/v1/events/{events[0]['id']}/snapshot").status_code == 200
        assert client.get("/api/v1/cameras/test/frame.jpg").status_code == 200
        assert client.get("/api/v1/events?start=2026-01-02&end=2026-01-01").status_code == 422
        assert client.get("/api/v1/events?start=not-a-date").status_code == 422
        assert client.get("/api/v1/events?limit=0").status_code == 422
        assert (
            client.put("/api/v1/cameras/test/enabled", json={"enabled": False}).status_code == 200
        )
        again = client.put("/api/v1/cameras/test/enabled", json={"enabled": True}).json()
        assert again["session_id"] != start["session_id"]
        manager = app.state.manager
    assert not manager.scheduler.thread.is_alive()


@pytest.mark.skipif(not (os.environ.get("FFMPEG_TEST_BIN") or shutil.which("ffmpeg")),
                    reason="FFmpeg required")
def test_complete_offline_render_with_real_video_and_fake_detector(tmp_path, video):
    config = load_config(write_config(tmp_path, video))
    config.streaming.ffmpeg_bin = os.environ.get("FFMPEG_TEST_BIN") or shutil.which("ffmpeg")
    output = tmp_path / "processed.mp4"
    result = render(config, config.cameras[0], output, FakeDetector(), fps=5)
    assert result["frames"] == 10
    assert result["duration_seconds"] == 2
    assert len(result["events"]) == 1
    assert (tmp_path / result["events"][0]["snapshot"]).is_file()
    assert json.loads(output.with_suffix(".events.json").read_text())["frames"] == 10
    capture = cv2.VideoCapture(str(output), cv2.CAP_FFMPEG, [cv2.CAP_PROP_N_THREADS, 1])
    assert capture.isOpened()
    try:
        fps = capture.get(cv2.CAP_PROP_FPS)
        decoded = 0
        while capture.read()[0]:
            decoded += 1
        assert decoded == 10 and abs(decoded / fps - 2) < 0.1
    finally:
        capture.release()


def test_event_utc_timestamp():
    event = EventCandidate("a", "s", 1, "car", "intrusion", "zone")
    assert datetime.fromisoformat(event.occurred_at).tzinfo == UTC
