import cv2
import numpy as np
import pytest

from app.config.schemas import CameraConfig, SourceConfig
from app.inference.types import Detection, Track


@pytest.fixture
def camera():
    return CameraConfig(
        id="test", source=SourceConfig(type="file", uri="test.avi"), output_path="test"
    )


@pytest.fixture
def video(tmp_path):
    path = tmp_path / "input.avi"
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), 10, (320, 240))
    assert writer.isOpened()
    for i in range(20):
        frame = np.zeros((240, 320, 3), np.uint8)
        cv2.rectangle(frame, (20 + i * 3, 60), (90 + i * 3, 130), (255, 255, 255), -1)
        writer.write(frame)
    writer.release()
    return path


def detection(x=20, y=50, class_id=2, name="car"):
    return Detection((x - 10, y - 20, x + 10, y), 0.9, class_id, name)


def track(x, y, track_id=1):
    return Track((x - 10, y - 20, x + 10, y), 0.9, 2, "car", track_id)
