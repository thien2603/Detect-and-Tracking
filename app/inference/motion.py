"""Time-aware Kalman/IoU tracker. Predictions are for display, never event evidence.

This is not ByteTrack: association is class-aware greedy IoU on predicted boxes.
The separate implementation leaves the original offline tracker unchanged.
"""

from dataclasses import dataclass

import cv2
import numpy as np

from app.inference.tracker import bbox_iou
from app.inference.types import Track


def measurement(box):
    x1, y1, x2, y2 = box
    return np.array([(x1 + x2) / 2, (y1 + y2) / 2,
                     max(1, x2 - x1), max(1, y2 - y1)], np.float32).reshape(4, 1)


def box_from_state(state):
    cx, cy, width, height = state[:4].reshape(-1)
    width, height = max(1, float(width)), max(1, float(height))
    return (float(cx) - width / 2, float(cy) - height / 2,
            float(cx) + width / 2, float(cy) + height / 2)


def transition(dt):
    matrix = np.eye(8, dtype=np.float32)
    matrix[:4, 4:] = np.eye(4, dtype=np.float32) * dt
    return matrix


@dataclass
class MotionState:
    track: Track
    filter: object
    timestamp: float
    observed_at: float
    missed: int = 0


class MotionIoUTracker:
    def __init__(self, iou_threshold=0.15, max_missed=8, max_age=0.6):
        self.iou_threshold, self.max_missed = iou_threshold, max_missed
        self.max_age = max_age
        self.states = {}
        self.next_id = 1

    def _new(self, detection, timestamp):
        track = Track(detection.bbox, detection.confidence, detection.class_id,
                      detection.class_name, self.next_id)
        self.next_id += 1
        kalman = cv2.KalmanFilter(8, 4)
        kalman.measurementMatrix = np.eye(4, 8, dtype=np.float32)
        kalman.measurementNoiseCov = np.eye(4, dtype=np.float32) * 2
        kalman.errorCovPost = np.diag([10.] * 4 + [1000.] * 4).astype(np.float32)
        kalman.statePost = np.vstack([measurement(track.bbox), np.zeros((4, 1), np.float32)])
        return MotionState(track, kalman, timestamp, timestamp)

    def update(self, detections, timestamp):
        predicted = {}
        for key in list(self.states):
            state = self.states[key]
            if timestamp - state.observed_at > self.max_age or timestamp < state.timestamp:
                del self.states[key]
                continue
            dt = timestamp - state.timestamp
            state.filter.transitionMatrix = transition(dt)
            state.filter.processNoiseCov = np.eye(8, dtype=np.float32) * max(dt, 0.001)
            predicted[key] = box_from_state(state.filter.predict())
            state.timestamp = timestamp
        candidates = []
        for key, box in predicted.items():
            for index, detection in enumerate(detections):
                score = bbox_iou(box, detection.bbox)
                if (self.states[key].track.class_id == detection.class_id
                        and score >= self.iou_threshold):
                    candidates.append((score, key, index))
        used_tracks, used_detections, visible = set(), set(), []
        for _, key, index in sorted(candidates, reverse=True):
            if key in used_tracks or index in used_detections:
                continue
            state, detection = self.states[key], detections[index]
            state.filter.correct(measurement(detection.bbox))
            # Event rules receive the measured box, not the smoothed/predicted box.
            state.track = Track(detection.bbox, detection.confidence, detection.class_id,
                                detection.class_name, key)
            state.observed_at, state.missed = timestamp, 0
            visible.append(state.track)
            used_tracks.add(key)
            used_detections.add(index)
        for key in list(self.states):
            if key not in used_tracks:
                self.states[key].missed += 1
                if self.states[key].missed > self.max_missed:
                    del self.states[key]
        for index, detection in enumerate(detections):
            if index not in used_detections:
                state = self._new(detection, timestamp)
                self.states[state.track.track_id] = state
                visible.append(state.track)
        return sorted(visible, key=lambda track: track.track_id)

    def predict(self, timestamp):
        tracks = []
        for key, state in self.states.items():
            age = timestamp - state.observed_at
            if age < 0 or age > self.max_age:
                continue
            # Non-mutating: rendering must not advance the measurement filter clock.
            estimate = transition(max(0, timestamp - state.timestamp)) @ state.filter.statePost
            box = box_from_state(estimate)
            tracks.append(Track(box, state.track.confidence, state.track.class_id,
                                state.track.class_name, key))
        return tracks

    def reset(self, reset_ids=False):
        self.states.clear()
        if reset_ids:
            self.next_id = 1
