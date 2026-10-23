from dataclasses import dataclass

from app.inference.types import Detection, Track


def bbox_iou(a, b):
    width = max(0, min(a[2], b[2]) - max(a[0], b[0]))
    height = max(0, min(a[3], b[3]) - max(a[1], b[1]))
    intersection = width * height
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - intersection
    return intersection / union if union > 0 else 0


@dataclass
class _State:
    track: Track
    missed: int = 0


class IoUTracker:
    """Class-aware greedy IoU association, independent for each camera."""

    def __init__(self, iou_threshold=0.15, max_missed=8):
        self.iou_threshold = iou_threshold
        self.max_missed = max_missed
        self.states: dict[int, _State] = {}
        self.next_id = 1

    def update(self, detections: list[Detection]) -> list[Track]:
        candidates = []
        for track_id, state in self.states.items():
            for index, detection in enumerate(detections):
                score = bbox_iou(state.track.bbox, detection.bbox)
                if state.track.class_id == detection.class_id and score >= self.iou_threshold:
                    candidates.append((score, track_id, index))
        used_tracks, used_detections = set(), set()
        visible = []
        for _, track_id, index in sorted(candidates, reverse=True):
            if track_id in used_tracks or index in used_detections:
                continue
            track = self._track(detections[index], track_id)
            self.states[track_id] = _State(track)
            visible.append(track)
            used_tracks.add(track_id)
            used_detections.add(index)
        for track_id in list(self.states):
            if track_id not in used_tracks:
                self.states[track_id].missed += 1
                if self.states[track_id].missed > self.max_missed:
                    del self.states[track_id]
        for index, detection in enumerate(detections):
            if index not in used_detections:
                track = self._track(detection, self.next_id)
                self.states[self.next_id] = _State(track)
                visible.append(track)
                self.next_id += 1
        return sorted(visible, key=lambda t: t.track_id)

    @staticmethod
    def _track(detection, track_id):
        return Track(
            detection.bbox, detection.confidence, detection.class_id, detection.class_name, track_id
        )

    def reset(self, reset_ids=False):
        self.states.clear()
        if reset_ids:
            self.next_id = 1
