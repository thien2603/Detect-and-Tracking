from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from uuid import uuid4


@dataclass
class EventCandidate:
    camera_id: str
    session_id: str
    track_id: int
    object_class: str
    event_type: str
    rule_id: str
    metadata: dict = field(default_factory=dict)
    video_seconds: float | None = None
    occurred_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    id: str = field(default_factory=lambda: uuid4().hex)
    snapshot: str | None = None

    def to_dict(self):
        return asdict(self)
