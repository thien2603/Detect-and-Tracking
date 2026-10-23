import os
import shutil

import cv2
import pytest

from app.config.schemas import AppConfig, CameraConfig, SourceConfig
from scripts.render_video import render
from tests.conftest import detection


@pytest.fixture
def render_config(video):
    ffmpeg = os.environ.get("FFMPEG_TEST_BIN") or shutil.which("ffmpeg")
    if not ffmpeg:
        pytest.skip("FFmpeg required")
    camera = CameraConfig(
        id="batch-test", source=SourceConfig(type="file", uri=str(video)),
        output_path="batch-test",
    )
    config = AppConfig(cameras=[camera])
    config.model.batch_size = 8
    config.streaming.ffmpeg_bin = ffmpeg
    return config


class BatchDetector:
    def __init__(self):
        self.batch_sizes = []

    def detect_batch(self, frames):
        self.batch_sizes.append(len(frames))
        return [[detection(x=60, y=100)] for _ in frames]


def test_batch_sampling_and_final_partial_batch(render_config, tmp_path):
    detector = BatchDetector()
    output = tmp_path / "batch.mp4"
    result = render(render_config, render_config.cameras[0], output, detector, fps=5)
    assert detector.batch_sizes == [8, 2]
    assert result["frames"] == 10 and result["duration_seconds"] == 2
    capture = cv2.VideoCapture(str(output))
    count = 0
    while capture.read()[0]:
        count += 1
    capture.release()
    assert count == 10


def test_batch_respects_time_limit(render_config, tmp_path):
    detector = BatchDetector()
    result = render(render_config, render_config.cameras[0], tmp_path / "short.mp4",
                    detector, fps=5, max_seconds=1)
    assert detector.batch_sizes == [5]
    assert result["frames"] == 5 and result["duration_seconds"] == 1


def test_invalid_batch_length_is_reported(render_config, tmp_path):
    class InvalidDetector:
        def detect_batch(self, frames):
            return []

    with pytest.raises(RuntimeError, match="invalid batch length"):
        render(render_config, render_config.cameras[0], tmp_path / "invalid.mp4",
               InvalidDetector(), fps=5)
