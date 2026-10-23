"""Fail on invalid local runtime dependencies before creating any worker threads."""

import shutil
import subprocess
from pathlib import Path

from app.config.loader import ConfigError


def validate_runtime(config, *, require_weights=True):
    if require_weights and not Path(config.model.weights).is_file():
        raise ConfigError(f"model.weights does not exist: {config.model.weights}. "
                          "Download the model first or correct the YAML path.")
    if config.streaming.enabled:
        binary = shutil.which(config.streaming.ffmpeg_bin)
        if binary is None:
            raise ConfigError("streaming.ffmpeg_bin is not an executable: "
                              f"{config.streaming.ffmpeg_bin}")
        try:
            subprocess.run([binary, "-version"], capture_output=True, timeout=5, check=True)
        except (OSError, subprocess.SubprocessError) as exc:
            raise ConfigError("streaming.ffmpeg_bin failed its -version check") from exc
        config.streaming.ffmpeg_bin = binary
    # Schedule validation belongs to startup too, not the first processed frame.
    from app.events.schedule import ZoneSchedule

    for camera in config.cameras:
        if camera.zone_schedule:
            try:
                ZoneSchedule(camera.zone_schedule)
            except (OSError, ValueError) as exc:
                raise ConfigError(f"Invalid zone_schedule for camera {camera.id}: {exc}") from exc
