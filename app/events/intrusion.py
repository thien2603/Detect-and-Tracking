from app.events.geometry import point_in_polygon


class IntrusionDetector:
    def __init__(self, zones):
        self.zones = zones
        self.states = {}

    def update(self, tracks, frame_number):
        events = []
        for zone in self.zones:
            for track in tracks:
                key = (zone.id, track.track_id)
                inside = point_in_polygon(track.anchor, zone.points)
                previous = self.states.get(key)
                if inside and (previous is None or not previous[0]):
                    reason = "first_seen_inside" if previous is None else "entry"
                    events.append((track, zone.id, reason))
                self.states[key] = (inside, frame_number)
        self.states = {
            key: value for key, value in self.states.items() if frame_number - value[1] <= 300
        }
        return events

    def reset(self):
        self.states.clear()
