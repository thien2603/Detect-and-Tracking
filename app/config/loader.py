from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import ValidationError

from app.config.schemas import AppConfig


class ConfigError(ValueError):
    pass


def load_config(path: str | Path, *, validate_sources: bool = True) -> AppConfig:
    path = Path(path).resolve()
    root = path.parent.parent
    try:
        config = AppConfig.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
    except (OSError, yaml.YAMLError, ValidationError) as exc:
        raise ConfigError(f"Cannot load {path}: {exc}") from exc

    def resolve(value):
        item = Path(value)
        return item if item.is_absolute() else root / item

    config.database.path = resolve(config.database.path)
    config.database.snapshot_dir = resolve(config.database.snapshot_dir)
    config.logging.file = resolve(config.logging.file)
    config.model.weights = str(resolve(config.model.weights))
    for camera in config.cameras:
        if camera.zone_schedule:
            camera.zone_schedule = str(resolve(camera.zone_schedule))
        if camera.source.type == "file":
            camera.source.uri = str(resolve(str(camera.source.uri)))
            if validate_sources and camera.enabled and not Path(camera.source.uri).is_file():
                raise ConfigError(
                    f"Missing source for {camera.id}: {camera.source.uri}. "
                    "Run the download script or update the camera URI."
                )
    return config
