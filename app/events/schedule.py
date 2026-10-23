import json
from pathlib import Path

from pydantic import Field, model_validator

from app.config.schemas import Point, StrictConfig, ZoneConfig


class Keyframe(StrictConfig):
    time: float = Field(ge=0)
    points: list[Point]

    @model_validator(mode="after")
    def valid_points(self):
        ZoneConfig(id="keyframe", points=self.points)
        return self


class Scene(StrictConfig):
    id: str
    start: float = Field(ge=0)
    end: float = Field(gt=0)
    keyframes: list[Keyframe] = Field(min_length=1)

    @model_validator(mode="after")
    def valid_interval(self):
        times = [k.time for k in self.keyframes]
        if self.start >= self.end or times != sorted(set(times)):
            raise ValueError("scene interval and ordered keyframe times must be valid")
        if times[0] > self.start or times[-1] < self.end:
            raise ValueError("keyframes must cover the whole scene interval")
        if len({len(k.points) for k in self.keyframes}) != 1:
            raise ValueError("keyframes must use the same number and order of vertices")
        return self


class ZoneSchedule:
    def __init__(self, path):
        self.scenes = [Scene.model_validate(x) for x in json.loads(Path(path).read_text())]
        for i, scene in enumerate(self.scenes):
            if i and scene.start < self.scenes[i - 1].end:
                raise ValueError("scene intervals must be sorted and not overlap")
        if len({s.id for s in self.scenes}) != len(self.scenes):
            raise ValueError("scene IDs must be unique")

    def at(self, seconds):
        for scene in self.scenes:
            if scene.start <= seconds < scene.end:
                keys = scene.keyframes
                left = max((k for k in keys if k.time <= seconds), key=lambda k: k.time)
                right = min((k for k in keys if k.time >= seconds), key=lambda k: k.time)
                fraction = (
                    (seconds - left.time) / (right.time - left.time)
                    if right.time != left.time
                    else 0
                )
                points = [
                    tuple(round(a[j] + fraction * (b[j] - a[j])) for j in (0, 1))
                    for a, b in zip(left.points, right.points, strict=True)
                ]
                return scene.id, [ZoneConfig(id="shoulder_watch", points=points)]
        return "unmonitored", []
