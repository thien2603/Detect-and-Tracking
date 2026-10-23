from app.events.geometry import crossing_within_segment, signed_distance


class LineCounter:
    def __init__(self, line):
        self.line = line
        self.states = {}
        self.counts = {"negative_to_positive": 0, "positive_to_negative": 0}

    def update(self, tracks, frame_number, seconds):
        events = []
        for track in tracks:
            point = track.anchor
            distance = signed_distance(point, self.line.start, self.line.end)
            if abs(distance) <= self.line.deadband_px:
                # Keep the last stable point outside the deadband.
                continue
            side = 1 if distance > 0 else -1
            old = self.states.get(track.track_id)
            last_crossing = old[2] if old else float("-inf")
            if (
                old
                and old[1] != side
                and (
                    seconds - last_crossing >= self.line.cooldown_seconds
                    and crossing_within_segment(old[0], point, self.line.start, self.line.end)
                )
            ):
                direction = "negative_to_positive" if side > 0 else "positive_to_negative"
                self.counts[direction] += 1
                events.append((track, direction))
                last_crossing = seconds
            self.states[track.track_id] = (point, side, last_crossing, frame_number)
        self.states = {k: v for k, v in self.states.items() if frame_number - v[3] <= 300}
        return events

    def reset(self):
        self.states.clear()
