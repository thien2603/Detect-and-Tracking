from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path

import cv2
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, ConfigDict

from app.config.loader import ConfigError, load_config
from app.config.preflight import validate_runtime
from app.events.repository import EventRepository, EventWriter
from app.inference.detector import YOLODetector
from app.manager import CameraManager

UTC = timezone.utc


class EnabledRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    enabled: bool


def create_app(config_path=None, *, detector=None):
    @asynccontextmanager
    async def lifespan(application):
        config = load_config(config_path or os.environ.get("CONFIG_PATH", "configs/config.yaml"))
        cv2.setNumThreads(config.model.opencv_threads)
        config.logging.file.parent.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(config.logging.file, maxBytes=10_000_000, backupCount=3)
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
        logger = logging.getLogger("app")
        logger.setLevel(config.logging.level)
        logger.addHandler(handler)
        logger.info("Starting service with %d configured cameras", len(config.cameras))
        repository = writer = manager = None
        try:
            validate_runtime(config, require_weights=detector is None)
            active_detector = detector if detector is not None else YOLODetector(config.model)
            if detector is None:
                try:
                    # Validate classes, device and weights before exposing a healthy API.
                    active_detector.load()
                except Exception as exc:
                    raise ConfigError(f"YOLO startup validation failed: {exc}") from exc
            repository = EventRepository(config.database.path, config.database.snapshot_dir)
            writer = EventWriter(repository)
            manager = CameraManager(config, active_detector, writer)
            active_detector = None  # Manager owns model lifetime; do not pin disabled prototypes.
            application.state.repository = repository
            application.state.manager = manager
            application.state.writer = writer
            manager.start()
            yield
        finally:
            if manager:
                manager.close()
            logger.info("Camera workers and inference scheduler stopped")
            if writer:
                writer.close()
            if repository:
                repository.close()
            logger.removeHandler(handler)
            handler.close()

    application = FastAPI(title="Vehicle tracking and zone alerts", lifespan=lifespan)

    @application.get("/health")
    def health():
        return {
            "status": "ok",
            "evidence_dropped": application.state.writer.dropped,
            "evidence_failed": application.state.writer.failed,
        }

    @application.get("/api/v1/cameras")
    def cameras():
        return application.state.manager.statuses()

    @application.put("/api/v1/cameras/{camera_id}/enabled")
    def enabled(camera_id: str, body: EnabledRequest):
        try:
            return application.state.manager.set_enabled(camera_id, body.enabled)
        except KeyError as exc:
            raise HTTPException(404, "Unknown camera") from exc

    @application.get("/api/v1/cameras/{camera_id}/frame.jpg")
    def frame(camera_id: str):
        try:
            data = application.state.manager.latest_jpeg(camera_id)
        except KeyError as exc:
            raise HTTPException(404, "Unknown camera") from exc
        if data is None:
            raise HTTPException(503, "No processed frame available yet")
        return Response(data, media_type="image/jpeg", headers={"Cache-Control": "no-store"})

    @application.get("/api/v1/events")
    def events(
        camera_id: str | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
        limit: int = Query(default=100, ge=1, le=1000),
    ):
        def utc(value):
            return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)

        start, end = utc(start) if start else None, utc(end) if end else None
        if start and end and start > end:
            raise HTTPException(422, "start must be before end")
        return application.state.repository.query(
            camera_id, start.isoformat() if start else None, end.isoformat() if end else None, limit
        )

    @application.get("/api/v1/events/{event_id}/snapshot")
    def snapshot(event_id: str):
        path = application.state.repository.snapshot_for(event_id)
        if not path or not Path(path).is_file():
            raise HTTPException(404, "Snapshot not found")
        return FileResponse(path, media_type="image/jpeg")

    return application


app = create_app()
