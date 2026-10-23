from app.config.loader import load_config
from app.config.schemas import ZoneConfig
from app.events.processor import EventProcessor
from app.events.region_counter import RegionCounter
from app.pipeline import AnalyticsPipeline
from tests.conftest import detection, track


def region():
    return ZoneConfig(id="count", points=[(40, 0), (100, 0), (100, 100), (40, 100)])


def test_entry_counted_once_per_id():
    counter = RegionCounter(region())
    assert counter.update([track(20, 50)], 0) == []
    assert len(counter.update([track(60, 50)], 1)) == 1
    assert counter.entries == 1 and counter.inside == 1
    assert counter.update([track(60, 50)], 2) == []
    assert counter.update([track(20, 50)], 3) == []
    assert counter.inside == 0
    assert counter.update([track(60, 50)], 4) == []
    assert counter.entries == 1


def test_initial_inside_not_an_entry_but_later_entry_observable():
    counter = RegionCounter(region())
    assert counter.update([track(60, 50)], 0) == []
    assert counter.entries == 0 and counter.first_seen_inside == 1
    counter.update([track(70, 50)], 1)
    assert counter.first_seen_inside == 1
    counter.update([track(20, 50)], 2)
    assert len(counter.update([track(60, 50)], 3)) == 1
    assert counter.entries == 1


def test_occupancy_and_independent_tracks():
    counter = RegionCounter(region())
    counter.update([track(20, 50, 1), track(20, 50, 2)], 0)
    assert len(counter.update([track(60, 50, 1), track(70, 50, 2)], 1)) == 2
    assert counter.entries == 2 and counter.inside == 2
    counter.update([], 2)
    assert counter.inside == 0 and counter.entries == 2


def test_processor_records_region_entry_without_changing_alerts(camera):
    camera.counting_region = region()
    camera.forbidden_zones = [ZoneConfig(id="red", points=[(110, 0), (150, 0),
                                                          (150, 100), (110, 100)])]
    processor = EventProcessor(camera, "session")
    processor.process([track(20, 50)], 0, 0)
    entry = processor.process([track(60, 50)], 1, 1, video_seconds=1)
    assert [event.event_type for event in entry] == ["region_entry"]
    assert entry[0].metadata["reason"] == "entry"
    alert = processor.process([track(120, 50)], 2, 2)
    assert [event.event_type for event in alert] == ["intrusion"]
    assert processor.counts["region_entries"] == 1


def test_pipeline_tracks_outside_green_to_observe_entry(camera):
    import numpy as np

    camera.counting_region = region()
    camera.tracker_iou_threshold = 0.05
    pipeline = AnalyticsPipeline(camera)
    frame = np.zeros((120, 180, 3), np.uint8)
    pipeline.process(frame, [detection(x=35)], 0)
    _, events, _ = pipeline.process(frame, [detection(x=45)], 0.1)
    assert any(event.event_type == "region_entry" for event in events)


def test_bellevue_runtime_layout_matches_approved_coordinates():
    import json
    from pathlib import Path

    config = load_config("configs/bellevue.yaml")
    geometry = json.loads(Path("configs/bellevue-regions.json").read_text())["cameras"]
    assert len(config.cameras) == 4
    for camera, draft in zip(config.cameras, geometry, strict=True):
        assert camera.detection_region is None
        assert camera.counting_region.model_dump(mode="json") == draft["counting_region"]
        zones = [zone.model_dump(mode="json") for zone in camera.forbidden_zones]
        assert zones == draft["forbidden_zones"]
