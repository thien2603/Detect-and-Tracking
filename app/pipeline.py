from collections import defaultdict, deque
from uuid import uuid4

from app.events.processor import EventProcessor
from app.events.schedule import ZoneSchedule
from app.inference.motion import MotionIoUTracker
from app.inference.region import filter_detections_by_region
from app.inference.tracker import IoUTracker
from app.streaming.annotator import annotate_frame


class AnalyticsPipeline:
    """Shared rules for offline rendering and the live multi-camera service."""

    def __init__(self, camera):
        self.camera = camera.model_copy(deep=True)
        self.session_id = uuid4().hex
        self.tracker = IoUTracker(camera.tracker_iou_threshold, camera.tracker_max_missed)
        if camera.tracker_motion:
            self.tracker = MotionIoUTracker(camera.tracker_iou_threshold, camera.tracker_max_missed,
                                           camera.prediction_max_age_ms / 1000)
        self.processor = EventProcessor(self.camera, self.session_id)
        self.schedule = ZoneSchedule(camera.zone_schedule) if camera.zone_schedule else None
        self.scene = None
        self.frame_number = 0
        self.alert_count = 0
        self.trails = defaultdict(lambda: deque(maxlen=25))
        self.last_seconds = None
        self.last_tracks = []
        self.last_observation = None
        self.last_render_tracks = []

    def process(self, frame, detections, seconds, fps=0, *, video_seconds=None):
        events, tracks = self.update(detections, seconds, video_seconds=video_seconds)
        return self.render(frame, seconds, fps, video_seconds=video_seconds), events, tracks

    def update(self, detections, seconds, *, video_seconds=None):
        """Only measured detections may update counters and generate evidence."""
        scene, zones = (
            self.schedule.at(seconds) if self.schedule else ("static", self.camera.forbidden_zones)
        )
        # A replay loop or a scene cut invalidates object identity across the cut.
        looped = self.last_seconds is not None and seconds < self.last_seconds
        if scene != self.scene or looped:
            self.tracker.reset()
            self.processor.reset()
            self.trails.clear()
        self.last_seconds, self.scene = seconds, scene
        self.camera.forbidden_zones = zones
        self.processor.intrusion_detector.zones = zones
        detections = filter_detections_by_region(detections, self.camera.detection_region)
        tracks = (self.tracker.update(detections, seconds) if self.camera.tracker_motion
                  else self.tracker.update(detections))
        self.last_tracks, self.last_observation = tracks, seconds
        events = self.processor.process(
            tracks, self.frame_number, seconds, video_seconds=video_seconds, scene=scene
        )
        self.alert_count += sum(e.event_type == "intrusion" for e in events)
        visible = {t.track_id for t in tracks}
        for track in tracks:
            self.trails[track.track_id].append(tuple(round(x) for x in track.anchor))
        if self.frame_number % 100 == 0:
            for key in list(self.trails):
                if key not in visible:
                    del self.trails[key]
        self.frame_number += 1
        return events, tracks

    def render(self, frame, seconds, fps=0, *, video_seconds=None, predict=False, output_size=None):
        """Draw on a fresh image without mutating event/tracker measurement state."""
        tracks = self.last_tracks
        stale = False
        if predict:
            tracks = (self.tracker.predict(seconds) if self.camera.tracker_motion else tracks)
            if (self.last_observation is None or seconds < self.last_observation
                    or (seconds - self.last_observation) * 1000
                    > self.camera.prediction_max_age_ms):
                tracks = []
                stale = True
        self.last_render_tracks = tracks
        return annotate_frame(
            frame,
            self.camera,
            tracks,
            self.processor.counts,
            fps,
            self.trails,
            self.alert_count,
            video_seconds,
            paused=self.schedule is not None and not self.camera.forbidden_zones,
            output_size=output_size,
            prediction_age_ms=(seconds - self.last_observation) * 1000
            if predict and self.last_observation is not None else None,
            prediction_stale=stale,
        )
