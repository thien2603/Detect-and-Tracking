"""Real sockets/codecs, synthetic detection: transport fault recovery, not YOLO performance."""

import os
import socket
import subprocess
import time
from threading import enumerate as threads

import numpy as np
import pytest
import yaml

from app.config.schemas import AppConfig, SourceConfig, StreamingConfig
from app.manager import CameraManager
from app.streaming.publisher import FFmpegPublisher
from benchmarks.probe import RTSPProbe
from tests.conftest import detection

FFMPEG = os.environ.get("FFMPEG_TEST_BIN")
MEDIAMTX = os.environ.get("MEDIAMTX_TEST_BIN")
pytestmark = pytest.mark.skipif(not (FFMPEG and MEDIAMTX),
                                reason="FFMPEG_TEST_BIN and MEDIAMTX_TEST_BIN required")


def wait_for(predicate, seconds=15):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.05)
    raise AssertionError("Timed out waiting for RTSP recovery")


@pytest.mark.timeout(90)
@pytest.mark.parametrize("mode", ["shared", "optimized", "per_camera"])
def test_four_rtsp_sources_reconnect_and_output_ffmpeg_restart(
        camera, tmp_path, monkeypatch, mode):
    optimized = mode == "optimized"
    monkeypatch.setenv("OPENCV_FFMPEG_CAPTURE_OPTIONS",
                       "rtsp_transport;tcp|fflags;nobuffer|flags;low_delay")
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    server = f"rtsp://127.0.0.1:{port}"
    path = tmp_path / "mediamtx.yml"
    path.write_text(yaml.safe_dump({
        "logLevel": "warn", "rtspAddress": f"127.0.0.1:{port}", "protocols": ["tcp"],
        "rtmp": False, "hls": False, "webrtc": False, "srt": False,
        "paths": {"all_others": None},
    }))
    sources = []
    manager = None
    output_probe = None
    scheduler_threads = []
    media = subprocess.Popen([MEDIAMTX, str(path)], stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL)
    try:
        time.sleep(0.5)
        assert media.poll() is None
        cameras = []
        for index in range(4):
            item = camera.model_copy(deep=True)
            item.id = item.output_path = f"integration{index}"
            item.tracker_motion = optimized
            item.source = SourceConfig(type="rtsp", uri=f"{server}/source/{item.id}",
                                       reconnect_seconds=0.1)
            cameras.append(item)
        source_config = StreamingConfig(enabled=True, rtsp_server=server, ffmpeg_bin=FFMPEG,
                                        output_fps=15)
        for item in cameras:
            sources.append(FFmpegPublisher(source_config, "source/" + item.id))
        config = AppConfig(cameras=cameras)
        config.streaming = StreamingConfig(enabled=True, rtsp_server=server + "/processed",
                                           ffmpeg_bin=FFMPEG, output_fps=12)
        config.model.batch_size = 4
        config.model.async_inference = optimized
        config.model.instances = "per_camera" if mode == "per_camera" else "shared"

        class Detector:
            def detect_batch(self, frames):
                return [[detection()] for _ in frames]

        class Writer:
            def submit(self, *_):
                pass

        # A separate feeder keeps the other sources publishing throughout the outage.
        from threading import Event, Thread

        stop_feed = Event()
        enabled = [True] * 4
        frame = np.zeros((240, 320, 3), np.uint8)

        def feed():
            while not stop_feed.wait(1 / 15):
                for index, source in enumerate(sources):
                    if enabled[index]:
                        source.submit(frame)

        feeder = Thread(target=feed, name="integration-feeder", daemon=True)
        feeder.start()
        manager = CameraManager(config, Detector(), Writer(), detector_factory=Detector)
        try:
            manager.start()
            scheduler_threads.extend(s.thread for s in manager.schedulers.values())
            if manager.scheduler:
                scheduler_threads.append(manager.scheduler.thread)
            wait_for(lambda: all(s["processed_frames"] >= 5 for s in manager.statuses()), 25)
            output_probe = RTSPProbe(f"{server}/processed/{cameras[0].output_path}", ffmpeg=FFMPEG)
            wait_for(lambda: output_probe.last_frame is not None, 15)
            enabled[0] = False
            sources[0].close()
            before = [s["processed_frames"] for s in manager.statuses()]
            wait_for(lambda: manager.statuses()[0]["reconnect_count"] > 0)
            wait_for(lambda: all(s["processed_frames"] >= before[i] + 3
                                for i, s in enumerate(manager.statuses()) if i > 0))
            # Recreate only the source this test owns; restore the same RTSP URI.
            sources[0] = FFmpegPublisher(source_config, "source/" + cameras[0].id)
            enabled[0] = True
            wait_for(lambda: manager.statuses()[0]["processed_frames"] >= before[0] + 5, 25)
            publisher = manager.workers[cameras[1].id].publisher
            wait_for(lambda: publisher.process is not None)
            old = publisher.process
            old_frames = publisher.frames
            old.kill()  # Exact child owned by this test, not an unrelated FFmpeg.
            wait_for(lambda: publisher.process is not None
                     and publisher.process.pid != old.pid and publisher.restarts >= 1
                     and publisher.frames > old_frames + 3)
            manager.set_enabled(cameras[2].id, False)
            assert not manager.statuses()[2]["enabled"]
            manager.set_enabled(cameras[2].id, True)
            wait_for(lambda: manager.statuses()[2]["processed_frames"] >= 3)
        finally:
            stop_feed.set()
            feeder.join(timeout=2)
    finally:
        if output_probe:
            output_probe.close()
        if manager:
            scheduler_threads.extend(s.thread for s in manager.schedulers.values())
            manager.close()
        for source in sources:
            source.close()
        media.terminate()
        media.wait(timeout=5)
    assert not any(t.name.startswith(("capture-integration", "analytics-integration",
                                     "publish-integration", "ffmpeg-watch-integration"))
                   for t in threads())
    assert scheduler_threads and not any(t.is_alive() for t in scheduler_threads)
