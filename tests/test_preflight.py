from threading import enumerate as threads
from types import SimpleNamespace

import numpy as np
import pytest
import yaml
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.config.loader import ConfigError, load_config
from app.config.preflight import validate_runtime
from app.config.schemas import AppConfig, ModelConfig, StreamingConfig
from app.inference.detector import YOLODetector
from app.main import create_app
from scripts.prepare_realtime_config import build_config
from tests.test_service import write_config


@pytest.mark.parametrize("values", [[], [" "], [-1]])
def test_invalid_model_classes_rejected(values):
    with pytest.raises(ValidationError):
        ModelConfig(classes=values)


@pytest.mark.parametrize("uri", ["http://host/x", "rtsp://", "rtsp://host:bad/x",
                                "rtsp://host:0/x", "rtsp://host/x?token=1"])
def test_invalid_output_url_rejected(uri):
    with pytest.raises(ValidationError):
        StreamingConfig(rtsp_server=uri)


def test_missing_weights_fail_preflight(camera, tmp_path):
    config = AppConfig(cameras=[camera])
    config.model.weights = str(tmp_path / "missing.pt")
    with pytest.raises(ConfigError, match="model.weights"):
        validate_runtime(config)


def test_missing_ffmpeg_fails_preflight(camera, tmp_path):
    config = AppConfig(cameras=[camera])
    config.streaming.enabled = True
    config.streaming.ffmpeg_bin = str(tmp_path / "missing-ffmpeg.exe")
    with pytest.raises(ConfigError, match="ffmpeg_bin"):
        validate_runtime(config, require_weights=False)


def test_model_failure_stops_startup_before_any_workers(tmp_path, video, monkeypatch):
    path = write_config(tmp_path, video, enabled=True)
    data = yaml.safe_load(path.read_text())
    weights = tmp_path / "dummy.pt"
    weights.write_bytes(b"test file, not an actual model")
    data["model"]["weights"] = str(weights)
    path.write_text(yaml.safe_dump(data))

    class InvalidDetector:
        def __init__(self, _):
            pass

        def load(self):
            raise ValueError("Unknown model class: invalid_test_class")

    monkeypatch.setattr("app.main.YOLODetector", InvalidDetector)
    before = {t.ident for t in threads()}
    with (pytest.raises(ConfigError, match="YOLO startup validation.*Unknown model class"),
          TestClient(create_app(path))):
        pytest.fail("A failed model must not expose a healthy API")
    assert not any(t.ident not in before and t.name.startswith(
        ("inference", "capture-", "analytics-", "publish-", "evidence")
    ) for t in threads())
    assert not load_config(path).database.path.exists()


def test_default_generation_preserves_all_five_cameras(camera):
    cameras = []
    for index in range(5):
        copy = camera.model_copy(deep=True)
        copy.id = copy.output_path = f"camera{index}"
        cameras.append(copy)
    result = build_config(AppConfig(cameras=cameras))
    assert [c["id"] for c in result["cameras"]] == [c.id for c in cameras]
    with pytest.raises(ValueError, match="positive"):
        build_config(AppConfig(cameras=cameras), 0)


def test_detector_transfers_all_boxes_once_per_image():
    class Tensor:
        transfers = 0

        def cpu(self):
            self.transfers += 1
            return self

        def tolist(self):
            return [[1, 2, 30, 40, 0.9, 0], [5, 6, 70, 80, 0.8, 2]]

    tensor = Tensor()
    output = SimpleNamespace(boxes=SimpleNamespace(data=tensor), names={0: "person", 2: "car"})
    detector = YOLODetector(ModelConfig(classes=["person", "car"]))
    detector._model = SimpleNamespace(predict=lambda **_: [output])
    detector._classes = [0, 2]
    detections = detector.detect_batch([np.zeros((100, 100, 3), np.uint8)])[0]
    assert tensor.transfers == 1
    assert [d.class_name for d in detections] == ["person", "car"]
    assert detections[1].bbox == (5, 6, 70, 80)


def test_concurrent_event_retry_is_atomic(tmp_path):
    from concurrent.futures import ThreadPoolExecutor

    from app.events.repository import EventRepository
    from app.events.types import EventCandidate

    repo = EventRepository(tmp_path / "events.db", tmp_path / "snapshots")
    event = EventCandidate("test", "session", 1, "person", "intrusion", "zone")
    try:
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda _: repo.save(event, np.zeros((30, 30, 3), np.uint8)),
                                    range(8)))
        assert results.count(True) == 1
        assert len(repo.query()) == 1
    finally:
        repo.close()
