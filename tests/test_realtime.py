import time
from threading import enumerate as threads

import cv2
import numpy as np

from app.camera.capture import CameraCapture
from app.config.schemas import AppConfig, SourceConfig
from app.events.repository import EventRepository
from app.events.types import EventCandidate
from app.inference.scheduler import InferenceScheduler
from app.manager import CameraManager
from app.streaming.publisher import prepare_output_frame
from app.telemetry import clear_time, read_time, stamp_time
from scripts.prepare_realtime_config import build_config
from tests.conftest import detection


def test_timestamp_round_trip_and_corruption():
    frame = np.zeros((240, 640, 3), np.uint8)
    now = round(time.time() * 1000)
    stamp_time(frame, now)
    assert read_time(frame) == now
    frame[-9:-2, :7] = 0
    assert read_time(frame) is None


def test_timestamp_survives_jpeg():
    frame = np.zeros((240, 640, 3), np.uint8)
    now = round(time.time() * 1000)
    stamp_time(frame, now)
    ok, encoded = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 70])
    assert ok and read_time(cv2.imdecode(encoded, cv2.IMREAD_COLOR)) == now


def test_missing_source_timestamp_is_not_replaced_with_a_forged_clock():
    frame = np.zeros((240, 640, 3), np.uint8)
    stamp_time(frame)
    assert read_time(frame) is not None
    clear_time(frame)
    assert read_time(frame) is None


def test_output_resize_preserves_aspect_and_original_timestamp():
    from app.config.schemas import StreamingConfig

    config = StreamingConfig(timestamp_overlay=True, max_output_width=960, max_output_height=540)
    frame = np.zeros((1100, 1200, 3), np.uint8)
    origin = round(time.time() * 1000) - 100
    stamp_time(frame, origin)
    resized, timestamp = prepare_output_frame(frame, config)
    assert resized.shape[:2] == (540, 588)
    assert timestamp == origin and read_time(resized) == origin
    assert frame.shape == (1100, 1200, 3)


def test_same_event_retry_is_idempotent(tmp_path):
    repo = EventRepository(tmp_path / "idempotent.db", tmp_path / "snapshots")
    try:
        event = EventCandidate("a", "s", 1, "person", "intrusion", "red")
        assert repo.save(event, np.zeros((50, 50, 3), np.uint8)) is True
        assert repo.save(event, np.zeros((50, 50, 3), np.uint8)) is False
        assert len(repo.query()) == 1
    finally:
        repo.close()


def test_rtsp_capture_recovers_after_exception(camera):
    camera.source = SourceConfig(type="rtsp", uri="rtsp://127.0.0.1/test",
                                 reconnect_seconds=0.1)
    capture = CameraCapture(camera)

    class FakeCapture:
        def isOpened(self):
            return True

        def get(self, _):
            return 30

        def read(self):
            capture.stop_event.set()
            return False, None

        def release(self):
            pass

    calls = []

    def open_source():
        calls.append(1)
        if len(calls) == 1:
            raise OSError("temporary failure")
        return FakeCapture()

    capture._open = open_source
    capture.start()
    capture.thread.join(timeout=2)
    assert len(calls) == 2 and capture.reconnect_count == 1
    assert not capture.thread.is_alive()


def test_batch_scheduler_coalesces_requests():
    class Detector:
        batches = []

        def detect_batch(self, frames):
            self.batches.append(len(frames))
            return [[] for _ in frames]

    detector = Detector()
    scheduler = InferenceScheduler(detector, batch_size=4, batch_wait_ms=20)
    try:
        futures = [scheduler.submit(str(index), None) for index in range(4)]
        assert all(future.result(timeout=2) == [] for future in futures)
        assert detector.batches == [4]
    finally:
        scheduler.close()


def test_manager_four_cameras_and_clean_shutdown(camera, video):
    cameras = []
    for index in range(4):
        item = camera.model_copy(deep=True)
        item.id, item.output_path = f"cam{index}", f"cam{index}"
        item.source = SourceConfig(type="file", uri=str(video), loop=True)
        cameras.append(item)
    config = AppConfig(cameras=cameras)
    config.model.batch_size = 4
    config.model.batch_wait_ms = 5

    class Detector:
        def detect_batch(self, frames):
            return [[detection()] for _ in frames]

    class Writer:
        def submit(self, *_):
            pass

    manager = CameraManager(config, Detector(), Writer())
    try:
        manager.start()
        deadline = time.monotonic() + 4
        while time.monotonic() < deadline:
            if all(status["processed_frames"] >= 3 for status in manager.statuses()):
                break
            time.sleep(0.02)
        assert all(status["processed_frames"] >= 3 for status in manager.statuses())
        manager.set_enabled("cam0", False)
        assert all(status["enabled"] for status in manager.statuses()[1:])
        assert manager.statuses()[0]["enabled"] is False
    finally:
        manager.close()
    assert not any(t.name.startswith(("capture-cam", "analytics-cam")) for t in threads())
    assert not manager.scheduler.thread.is_alive()


def test_generated_rtsp_and_stress_configs(camera):
    base = AppConfig(cameras=[camera])
    result = AppConfig.model_validate(build_config(base, 8, rtsp_server="rtsp://127.0.0.1:8554"))
    assert len({item.id for item in result.cameras}) == 8
    assert len({item.output_path for item in result.cameras}) == 8
    assert all(item.source.type == "rtsp" for item in result.cameras)
    assert result.streaming.output_fps >= 10


def test_worker_does_not_relabel_capture_clock_as_replay_origin(camera, video):
    camera.source = SourceConfig(type="file", uri=str(video), loop=True)
    config = AppConfig(cameras=[camera])
    config.streaming.timestamp_overlay = True

    class Detector:
        def detect_batch(self, frames):
            return [[] for _ in frames]

    class Writer:
        def submit(self, *_):
            pass

    manager = CameraManager(config, Detector(), Writer())
    try:
        manager.start()
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline and manager.statuses()[0]["processed_frames"] == 0:
            time.sleep(0.02)
        status = manager.statuses()[0]
        assert status["processed_frames"] > 0
        assert status["source_marker_frames"] == 0 and status["source_marker_misses"] > 0
        assert status["source_timestamp_origin"] == "capture"
        jpeg = manager.latest_jpeg(camera.id)
        assert read_time(cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_COLOR)) is None
    finally:
        manager.close()
