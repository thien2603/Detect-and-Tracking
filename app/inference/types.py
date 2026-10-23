from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Detection:
    bbox: tuple[float, float, float, float]
    confidence: float
    class_id: int
    class_name: str


@dataclass(frozen=True, slots=True)
class Track(Detection):
    track_id: int

    @property
    def anchor(self) -> tuple[float, float]:
        return ((self.bbox[0] + self.bbox[2]) / 2, self.bbox[3])
