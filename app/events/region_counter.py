from app.events.geometry import point_in_polygon


class RegionCounter:
    """Count one observed outside-to-inside transition per track ID.

    A track first detected inside is reported separately, not called an entry.
    Tracking must also observe vehicles outside this region for entry detection.
    """

    def __init__(self, region):
        self.region = region
        self.states = {}
        self.counted = set()
        self.entries = 0
        self.inside = 0
        self.first_seen_inside = 0

    def update(self, tracks, frame_number):
        entering = []
        self.inside = 0
        for track in tracks:
            inside = point_in_polygon(track.anchor, self.region.points)
            self.inside += int(inside)
            old = self.states.get(track.track_id)
            if old is None and inside:
                self.first_seen_inside += 1
            elif old is not None and not old[0] and inside and track.track_id not in self.counted:
                self.entries += 1
                self.counted.add(track.track_id)
                entering.append(track)
            self.states[track.track_id] = (inside, frame_number)
        self.states = {
            key: value for key, value in self.states.items()
            if frame_number - value[1] <= 300
        }
        return entering

    def reset(self):
        # Match the line counter: keep cumulative totals across scene/loop resets.
        self.states.clear()
        self.counted.clear()
        self.inside = 0
