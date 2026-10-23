from __future__ import annotations

from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Point = tuple[int, int]


def validate_rtsp_uri(value, *, allow_query=True):
    try:
        parsed = urlsplit(value)
        port = parsed.port
        if (parsed.scheme not in {"rtsp", "rtsps"} or not parsed.hostname
                or parsed.fragment or (parsed.query and not allow_query)
                or (port is not None and port == 0)):
            raise ValueError
    except ValueError as exc:
        raise ValueError("Expected RTSP URI with a valid rtsp(s) scheme, host and port; "
                         "output base URLs cannot contain query/fragment") from exc
    return value


class StrictConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ModelConfig(StrictConfig):
    weights: str = Field(default="models/yolo11n.pt", min_length=1)
    confidence: float = Field(default=0.25, gt=0, le=1)
    imgsz: int = Field(default=640, ge=160, le=1280)
    classes: list[str | int] = Field(default_factory=lambda: ["car"], min_length=1)
    device: str = Field(default="cpu", pattern=r"^(cpu|mps|(?:cuda:)?[0-9]+)$")
    torch_threads: int = Field(default=2, ge=1)
    opencv_threads: int = Field(default=1, ge=1, le=16)
    batch_size: int = Field(default=1, ge=1, le=32)
    batch_wait_ms: float = Field(default=0, ge=0, le=50)
    half: bool = False
    async_inference: bool = False
    detect_interval: int = Field(default=1, ge=1, le=30)
    rect: bool = True
    instances: Literal["shared", "per_camera"] = "shared"
    cuda_streams: bool = False

    @field_validator("classes")
    @classmethod
    def valid_classes(cls, values):
        if any((isinstance(v, str) and not v.strip())
               or (isinstance(v, int) and v < 0) for v in values):
            raise ValueError("classes must contain non-empty names or non-negative IDs")
        return [v.strip() if isinstance(v, str) else v for v in values]


class SourceConfig(StrictConfig):
    type: Literal["file", "rtsp", "webcam"]
    uri: str | int
    loop: bool = False
    reconnect_seconds: float = Field(default=2, ge=0.1, le=60)

    @model_validator(mode="after")
    def valid_uri(self):
        if self.type == "webcam":
            if int(self.uri) < 0:
                raise ValueError("webcam index must be non-negative")
        elif not isinstance(self.uri, str) or not self.uri.strip():
            raise ValueError("file/RTSP URI must be a non-empty string")
        if self.type == "rtsp":
            validate_rtsp_uri(str(self.uri))
        return self


class ZoneConfig(StrictConfig):
    id: str = Field(pattern=r"^[A-Za-z0-9_-]+$")
    points: list[Point]

    @field_validator("points")
    @classmethod
    def valid_polygon(cls, points):
        if len(points) < 3:
            raise ValueError("a polygon needs at least 3 points")
        area = sum(
            x * points[(i + 1) % len(points)][1] - points[(i + 1) % len(points)][0] * y
            for i, (x, y) in enumerate(points)
        )
        if area == 0:
            raise ValueError("polygon must have non-zero area")
        return points


class LineConfig(StrictConfig):
    id: str = "count_line"
    start: Point
    end: Point
    deadband_px: float = Field(default=4, ge=0)
    cooldown_seconds: float = Field(default=0.75, ge=0)

    @model_validator(mode="after")
    def distinct_endpoints(self):
        if self.start == self.end:
            raise ValueError("line endpoints must differ")
        return self


class CameraConfig(StrictConfig):
    id: str = Field(pattern=r"^[A-Za-z0-9_-]+$")
    enabled: bool = True
    source: SourceConfig
    output_path: str = Field(pattern=r"^[A-Za-z0-9_-]+(?:/[A-Za-z0-9_-]+)*$")
    detection_region: ZoneConfig | None = None
    counting_region: ZoneConfig | None = None
    line: LineConfig | None = None
    forbidden_zones: list[ZoneConfig] = Field(default_factory=list)
    zone_schedule: str | None = None
    tracker_iou_threshold: float = Field(default=0.15, gt=0, le=1)
    tracker_max_missed: int = Field(default=8, ge=1, le=300)
    tracker_motion: bool = False
    prediction_max_age_ms: float = Field(default=600, ge=0, le=2000)

    @model_validator(mode="after")
    def valid_rules(self):
        ids = [z.id for z in self.forbidden_zones]
        if len(ids) != len(set(ids)):
            raise ValueError("zone IDs must be unique within each camera")
        if self.zone_schedule and self.source.type != "file":
            raise ValueError("time-based zone schedules require a file source")
        return self


class StreamingConfig(StrictConfig):
    enabled: bool = False
    rtsp_server: str = "rtsp://localhost:8554/processed"
    output_fps: float = Field(default=10, ge=1, le=60)
    ffmpeg_bin: str = "ffmpeg"
    preset: str = "ultrafast"
    max_frame_age_ms: float = Field(default=800, ge=100, le=10000)
    timestamp_overlay: bool = False
    max_output_width: int | None = Field(default=None, ge=320, le=4096, multiple_of=2)
    max_output_height: int | None = Field(default=None, ge=240, le=4096, multiple_of=2)
    encoder: Literal["libx264", "h264_nvenc", "auto"] = "libx264"

    @field_validator("rtsp_server")
    @classmethod
    def valid_server(cls, value):
        return validate_rtsp_uri(value, allow_query=False)


class DatabaseConfig(StrictConfig):
    path: Path = Path("data/database/events.db")
    snapshot_dir: Path = Path("data/snapshots")


class ApiConfig(StrictConfig):
    host: str = "0.0.0.0"
    port: int = Field(default=8000, ge=1, le=65535)


class LoggingConfig(StrictConfig):
    level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    file: Path = Path("logs/app.log")
    metrics_interval_seconds: float = Field(default=5, ge=0.2, le=300)


class AppConfig(StrictConfig):
    model: ModelConfig = Field(default_factory=ModelConfig)
    streaming: StreamingConfig = Field(default_factory=StreamingConfig)
    database: DatabaseConfig = Field(default_factory=DatabaseConfig)
    api: ApiConfig = Field(default_factory=ApiConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    cameras: list[CameraConfig] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_cameras(self):
        for key in ("id", "output_path"):
            values = [getattr(c, key) for c in self.cameras]
            if len(values) != len(set(values)):
                raise ValueError(f"duplicate camera {key}")
        return self
