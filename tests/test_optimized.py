import time
from threading import Event, current_thread
from threading import enumerate as threads

import numpy as np
import pytest

from app.config.schemas import AppConfig, SourceConfig, StreamingConfig, ZoneConfig
from app.inference.detector import YOLODetector
from app.inference.motion import MotionIoUTracker
from app.inference.scheduler import InferenceScheduler
from app.manager import CameraManager
from app.pipeline import AnalyticsPipeline
from app.streaming.publisher import FFmpegPublisher, encoder_arguments, probe_nvenc
from tests.conftest import detection


def test_motion_matches_fast_vehicle_after_learning_velocity():
    tracker = MotionIoUTracker(max_age=1)
    first = tracker.update([detection(x=10)], 0)[0]
    tracker.update([detection(x=18)], 0.1)
    tracker.update([detection(x=26)], 0.2)
    # No overlap with the previous measured box; predicted position does overlap.
    assert tracker.update([detection(x=66)], 0.7)[0].track_id == first.track_id


def test_prediction_is_bounded_non_mutating_and_class_aware():
    tracker = MotionIoUTracker(max_age=0.5)
    first = tracker.update([detection(x=10)], 0)[0]
    tracker.update([detection(x=18)], 0.1)
    state = tracker.states[first.track_id]
    original = state.filter.statePost.copy()
    assert tracker.predict(0.2)[0].bbox[0] > state.track.bbox[0]
    assert tracker.predict(0.3)
    assert np.array_equal(original, state.filter.statePost)
    assert state.timestamp == 0.1
    assert tracker.predict(0.7) == [] and tracker.predict(-1) == []
    other = tracker.update([detection(x=18, class_id=0, name="person")], 0.2)[0]
    assert other.track_id != first.track_id


def test_motion_expiry_and_reset_never_recycle_ids():
    tracker = MotionIoUTracker(max_age=0.2)
    first = tracker.update([detection()], 0)[0]
    second = tracker.update([detection()], 1)[0]
    tracker.reset()
    third = tracker.update([detection()], 2)[0]
    assert first.track_id < second.track_id < third.track_id


def test_predictions_never_generate_events_or_change_counts(camera):
    camera.tracker_motion = True
    camera.forbidden_zones = [ZoneConfig(id="red", points=[(40, 0), (100, 0),
                                                         (100, 100), (40, 100)])]
    pipeline = AnalyticsPipeline(camera)
    pipeline.update([detection(x=30)], 0)
    pipeline.update([detection(x=38)], 0.1)
    counts = dict(pipeline.processor.counts)
    frame = np.zeros((240, 320, 3), np.uint8)
    for seconds in (0.2, 0.3, 0.4):
        pipeline.render(frame, seconds, predict=True)
    assert pipeline.alert_count == 0
    assert dict(pipeline.processor.counts) == counts
    events, _ = pipeline.update([detection(x=46)], 0.2)
    assert len(events) == 1 and events[0].event_type == "intrusion"


def test_scaled_render_preserves_measurement_geometry(camera):
    camera.counting_region = ZoneConfig(id="count", points=[(0, 0), (320, 0),
                                                           (320, 240), (0, 240)])
    pipeline = AnalyticsPipeline(camera)
    pipeline.update([detection(x=100)], 0)
    original_box = pipeline.last_tracks[0].bbox
    frame = np.zeros((480, 640, 3), np.uint8)
    canvas = pipeline.render(frame, 0, output_size=(320, 240))
    assert canvas.shape[:2] == (240, 320)
    assert pipeline.last_tracks[0].bbox == original_box
    assert pipeline.camera.counting_region.points[1] == (320, 0)
    assert not np.any(frame)


def test_async_renders_fresh_frames_while_detector_is_busy(camera, video):
    camera.source = SourceConfig(type="file", uri=str(video), loop=True)
    camera.tracker_motion = True
    config = AppConfig(cameras=[camera])
    config.model.async_inference = True
    config.model.detect_interval = 2
    started, release = Event(), Event()

    class Detector:
        def detect_batch(self, frames):
            started.set()
            assert release.wait(3)
            return [[detection()] for _ in frames]

    class Writer:
        def submit(self, *_):
            pass

    manager = CameraManager(config, Detector(), Writer())
    try:
        manager.start()
        assert started.wait(2)
        time.sleep(0.45)
        worker = manager.workers[camera.id]
        assert worker.rendered >= 3 and worker.detected == 0
        # No background JPEG encoding when the API preview is unused.
        assert worker.last_jpeg is None
        first_canvas = worker.last_canvas
        assert manager.latest_jpeg(camera.id)
        release.set()
        deadline = time.monotonic() + 2
        while worker.detected == 0 and time.monotonic() < deadline:
            time.sleep(0.01)
        assert worker.detected > 0 and worker.rendered > worker.detected
        deadline = time.monotonic() + 1
        while worker.last_canvas is first_canvas and time.monotonic() < deadline:
            time.sleep(0.01)
        assert worker.last_canvas is not first_canvas
    finally:
        release.set()
        manager.close()
    assert not worker.thread.is_alive() and not manager.scheduler.thread.is_alive()


def test_nvenc_probe_tests_actual_encoding_and_caches_failure(monkeypatch):
    calls = []

    class Failed:
        returncode = 1
        stderr = b"Driver does not support required nvenc API"

    def run(command, **kwargs):
        calls.append(command)
        return Failed()

    monkeypatch.setattr("app.streaming.publisher.subprocess.run", run)
    probe_nvenc.cache_clear()
    try:
        supported, diagnostic = probe_nvenc("test-ffmpeg")
        assert not supported and "Driver" in diagnostic
        assert probe_nvenc("test-ffmpeg")[0] is False and len(calls) == 1
        assert "-frames:v" in calls[0] and "h264_nvenc" in calls[0]
        assert "zerolatency" not in encoder_arguments("h264_nvenc")
        assert "zerolatency" in encoder_arguments("libx264")
    finally:
        probe_nvenc.cache_clear()


def test_auto_falls_back_after_runtime_failure_but_explicit_encoder_does_not():
    publisher = FFmpegPublisher.__new__(FFmpegPublisher)
    publisher.config = StreamingConfig(encoder="auto")
    publisher.path, publisher.encoder = "test", "h264_nvenc"
    publisher.encoder_diagnostic = "session limit"
    publisher._fallback_encoder("failure")
    assert publisher.encoder == "libx264"
    publisher.config.encoder = "h264_nvenc"
    publisher.encoder = "h264_nvenc"
    publisher._fallback_encoder("failure")
    assert publisher.encoder == "h264_nvenc"


def test_warmup_covers_microbatch_shapes_without_camera_threads(camera, monkeypatch):
    config = AppConfig(cameras=[camera])
    config.model.imgsz = 480
    detector = YOLODetector(config.model)
    shapes = []
    monkeypatch.setattr(detector, "detect_batch",
                        lambda frames: shapes.append((len(frames), frames[0].shape)))
    detector.warmup(4)
    assert shapes == [(size, (480, 480, 3)) for size in range(1, 5)]


def test_scheduler_warms_on_inference_thread_before_accepting_cameras():
    warmed = []

    class Detector:
        def warmup(self, count):
            warmed.append((count, current_thread().name))

        def detect_batch(self, frames):
            return [[] for _ in frames]

    scheduler = InferenceScheduler(Detector(), 4, 5, warmup=True)
    try:
        assert warmed == [(4, "inference")] and scheduler.ready.is_set()
        assert scheduler.submit("a", None).result(timeout=2) == []
    finally:
        scheduler.close()


def test_failed_warmup_leaves_no_inference_thread():
    before = {thread.ident for thread in threads()}

    class Detector:
        def warmup(self, count):
            raise ValueError("CUDA startup failure")

    with pytest.raises(RuntimeError, match="Inference warmup failed: CUDA startup failure"):
        InferenceScheduler(Detector(), warmup=True)
    assert not [thread for thread in threads()
                if thread.ident not in before and thread.name == "inference"]
