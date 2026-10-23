import json

import pytest
from pydantic import ValidationError

from app.config.schemas import LineConfig, ZoneConfig
from app.events.geometry import point_in_polygon
from app.events.intrusion import IntrusionDetector
from app.events.line_counter import LineCounter
from app.events.schedule import ZoneSchedule
from app.inference.region import filter_detections_by_region
from app.inference.tracker import IoUTracker, bbox_iou
from tests.conftest import detection, track

SQUARE = [(40, 0), (100, 0), (100, 100), (40, 100)]


@pytest.mark.parametrize(
    "point,expected", [((60, 50), True), ((0, 50), False), ((40, 0), True), ((100, 40), True)]
)
def test_polygon_boundary(point, expected):
    assert point_in_polygon(point, SQUARE) is expected


def test_zero_area_rejected():
    with pytest.raises(ValidationError):
        ZoneConfig(id="x", points=[(0, 0), (1, 1), (2, 2)])


def test_iou():
    assert bbox_iou((0, 0, 10, 10), (0, 0, 10, 10)) == 1
    assert bbox_iou((0, 0, 10, 10), (20, 20, 30, 30)) == 0


def test_tracker_preserves_id_after_brief_miss():
    tracker = IoUTracker()
    first = tracker.update([detection()])[0]
    tracker.update([])
    assert tracker.update([detection(x=22)])[0].track_id == first.track_id


def test_tracker_never_matches_different_class():
    tracker = IoUTracker()
    first = tracker.update([detection()])[0]
    second = tracker.update([detection(class_id=3, name="motorcycle")])[0]
    assert second.track_id != first.track_id


def test_tracker_expiry_and_scene_reset_keep_ids_unique():
    tracker = IoUTracker(max_missed=1)
    first = tracker.update([detection()])[0]
    tracker.update([])
    tracker.update([])
    second = tracker.update([detection()])[0]
    tracker.reset()
    third = tracker.update([detection()])[0]
    assert first.track_id < second.track_id < third.track_id


def test_region_uses_bottom_center():
    zone = ZoneConfig(id="road", points=SQUARE)
    assert filter_detections_by_region([detection(x=45)], zone)
    assert not filter_detections_by_region([detection(x=35)], zone)


def test_entry_stay_exit_reentry():
    detector = IntrusionDetector([ZoneConfig(id="zone", points=SQUARE)])
    assert detector.update([track(20, 50)], 0) == []
    assert detector.update([track(50, 50)], 1)[0][2] == "entry"
    assert detector.update([track(60, 50)], 2) == []
    assert detector.update([track(20, 50)], 3) == []
    assert detector.update([track(60, 50)], 4)[0][2] == "entry"


def test_first_seen_inside_not_called_entry():
    detector = IntrusionDetector([ZoneConfig(id="zone", points=SQUARE)])
    assert detector.update([track(60, 50)], 0)[0][2] == "first_seen_inside"


def test_line_crossing_survives_deadband():
    counter = LineCounter(LineConfig(start=(0, 50), end=(100, 50), deadband_px=4))
    assert not counter.update([track(50, 40)], 0, 0)
    assert not counter.update([track(50, 49)], 1, 0.1)
    assert not counter.update([track(50, 52)], 2, 0.2)
    assert counter.update([track(50, 60)], 3, 1)[0][1] == "negative_to_positive"


def test_line_is_finite_and_cooldown_applies():
    counter = LineCounter(LineConfig(start=(0, 50), end=(100, 50)))
    counter.update([track(150, 40)], 0, 0)
    assert not counter.update([track(150, 60)], 1, 1)
    counter.update([track(50, 40, 2)], 2, 2)
    assert counter.update([track(50, 60, 2)], 3, 3)
    assert not counter.update([track(50, 40, 2)], 4, 3.1)


def test_schedule_interpolates_and_pauses(tmp_path):
    path = tmp_path / "zones.json"
    path.write_text(
        json.dumps(
            [
                {
                    "id": "scene",
                    "start": 2,
                    "end": 4,
                    "keyframes": [
                        {"time": 2, "points": [[0, 0], [10, 0], [10, 10], [0, 10]]},
                        {"time": 4, "points": [[10, 0], [20, 0], [20, 10], [10, 10]]},
                    ],
                }
            ]
        )
    )
    schedule = ZoneSchedule(path)
    assert schedule.at(1) == ("unmonitored", [])
    assert schedule.at(3)[1][0].points[0] == (5, 0)
    assert schedule.at(4) == ("unmonitored", [])


def test_supplied_schedule_valid():
    schedule = ZoneSchedule("configs/vietnam-expressway-zones.json")
    assert schedule.at(60)[0] == "hanoi_haiphong"


def test_schedule_rejects_overlap(tmp_path):
    path = tmp_path / "zones.json"
    scene = {
        "id": "a",
        "start": 0,
        "end": 5,
        "keyframes": [{"time": 0, "points": SQUARE}, {"time": 10, "points": SQUARE}],
    }
    path.write_text(json.dumps([scene, {**scene, "id": "b", "start": 4}]))
    with pytest.raises(ValueError):
        ZoneSchedule(path)
