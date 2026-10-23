import gc
import sys
import time
import weakref
from threading import Barrier, BrokenBarrierError
from types import SimpleNamespace

import pytest

from app.config.schemas import AppConfig, ModelConfig, SourceConfig
from app.inference.detector import YOLODetector
from app.manager import CameraManager
from tests.conftest import detection


def four_camera_config(camera, video):
    cameras = []
    for index in range(4):
        item = camera.model_copy(deep=True)
        item.id = item.output_path = f"independent{index}"
        item.source = SourceConfig(type="file", uri=str(video), loop=True)
        cameras.append(item)
    config = AppConfig(cameras=cameras)
    config.model.instances = "per_camera"
    return config


class Writer:
    def submit(self, *_):
        pass


def test_four_distinct_models_can_enter_inference_concurrently(camera, video):
    config = four_camera_config(camera, video)
    barrier = Barrier(4)
    warmups = []

    class Detector:
        first = True

        def warmup(self, count):
            assert count == 1
            warmups.append(self)

        def detect_batch(self, frames):
            assert len(frames) == 1 and len(warmups) >= 4
            if self.first:
                self.first = False
                try:
                    barrier.wait(timeout=3)
                except BrokenBarrierError as exc:
                    raise AssertionError("Models were serialized by a shared scheduler") from exc
            return [[detection()]]

    manager = CameraManager(config, Detector(), Writer(), detector_factory=Detector)
    schedulers = []
    try:
        manager.start()
        schedulers = list(manager.schedulers.values())
        assert manager.scheduler is None
        assert len({id(s.detector) for s in schedulers}) == 4
        deadline = time.monotonic() + 4
        while time.monotonic() < deadline:
            if all(status["processed_frames"] >= 2 for status in manager.statuses()):
                break
            time.sleep(0.01)
        assert all(status["processed_frames"] >= 2 for status in manager.statuses())
        assert len({status["model_instance"] for status in manager.statuses()}) == 4
        manager.set_enabled("independent0", False)
        assert not schedulers[0].thread.is_alive()
        assert all(s.thread.is_alive() for s in schedulers[1:])
        manager.set_enabled("independent0", True)
        assert manager.schedulers["independent0"] is not schedulers[0]
        schedulers.append(manager.schedulers["independent0"])
    finally:
        manager.close()
    assert not any(s.thread.is_alive() for s in schedulers)


def test_failed_second_model_startup_closes_first_scheduler(camera, video):
    config = four_camera_config(camera, video)

    class Detector:
        def detect_batch(self, frames):
            return [[] for _ in frames]

    class FailedDetector(Detector):
        def load(self):
            raise RuntimeError("CUDA out of memory")

    manager = CameraManager(config, Detector(), Writer(), detector_factory=FailedDetector)
    with pytest.raises(RuntimeError, match="CUDA out of memory"):
        manager.start()
    assert manager.workers == {} and manager.schedulers == {}
    manager.close()


def test_independent_mode_requires_a_model_factory(camera):
    config = AppConfig(cameras=[camera])
    config.model.instances = "per_camera"
    with pytest.raises(ValueError, match="detector.clone"):
        CameraManager(config, object(), Writer())


def test_detector_clone_has_independent_config_and_no_shared_predictor():
    detector = YOLODetector(ModelConfig(classes=["car"], instances="per_camera"))
    detector._model = object()
    clone = detector.clone()
    clone.config.classes.append("person")
    assert clone._model is None and clone._lock is not detector._lock
    assert detector.config.classes == ["car"]


def test_dedicated_stream_wraps_prediction_and_cpu_result_collection(monkeypatch):
    events = []

    class Context:
        def __enter__(self):
            events.append("enter")

        def __exit__(self, *_):
            events.append("exit")

    detector = YOLODetector(ModelConfig())
    detector._model = object()
    detector._cuda_stream = object()

    def collect(frames):
        assert events == ["enter"]
        return [[] for _ in frames]

    monkeypatch.setitem(sys.modules, "torch", SimpleNamespace(
        cuda=SimpleNamespace(stream=lambda stream: Context())))
    monkeypatch.setattr(detector, "_predict_and_collect", collect)
    assert detector.detect_batch([None]) == [[]]
    assert events == ["enter", "exit"]


def test_clone_factory_does_not_pin_the_original_model():
    detector = YOLODetector(ModelConfig(instances="per_camera"))
    original = weakref.ref(detector)
    factory = detector.clone_factory()
    del detector
    gc.collect()
    assert original() is None
    assert factory().config.instances == "per_camera"
