from app.events.intrusion import IntrusionDetector
from app.events.line_counter import LineCounter
from app.events.region_counter import RegionCounter
from app.events.types import EventCandidate


class EventProcessor:
    def __init__(self, camera, session_id):
        self.camera = camera
        self.session_id = session_id
        self.intrusion_detector = IntrusionDetector(camera.forbidden_zones)
        self.line_counter = LineCounter(camera.line) if camera.line else None
        self.region_counter = (
            RegionCounter(camera.counting_region) if camera.counting_region else None
        )

    def process(self, tracks, frame_number, seconds, *, video_seconds=None, scene=None):
        events = []
        if self.region_counter:
            for track in self.region_counter.update(tracks, frame_number):
                events.append(
                    self._event(
                        track, "region_entry", self.camera.counting_region.id, video_seconds,
                        {"reason": "entry", "scene": scene, "count_once_per_track": True},
                    )
                )
        if self.line_counter:
            for track, direction in self.line_counter.update(tracks, frame_number, seconds):
                events.append(
                    self._event(
                        track,
                        "line_crossing",
                        self.camera.line.id,
                        video_seconds,
                        {"direction": direction, "scene": scene},
                    )
                )
        for track, zone, reason in self.intrusion_detector.update(tracks, frame_number):
            events.append(
                self._event(
                    track, "intrusion", zone, video_seconds, {"reason": reason, "scene": scene}
                )
            )
        return events

    def _event(self, track, kind, rule, seconds, metadata):
        return EventCandidate(
            self.camera.id,
            self.session_id,
            track.track_id,
            track.class_name,
            kind,
            rule,
            metadata,
            seconds,
        )

    @property
    def counts(self):
        counts = dict(self.line_counter.counts) if self.line_counter else {
            "negative_to_positive": 0, "positive_to_negative": 0
        }
        if self.region_counter:
            counts.update({
                "region_entries": self.region_counter.entries,
                "region_inside": self.region_counter.inside,
                "region_first_seen_inside": self.region_counter.first_seen_inside,
            })
        return counts

    def reset(self):
        self.intrusion_detector.reset()
        if self.line_counter:
            self.line_counter.reset()
        if self.region_counter:
            self.region_counter.reset()
