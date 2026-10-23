from pathlib import Path

import numpy as np
import yaml

from app.config.schemas import AppConfig
from scripts.record_demo import tile


def test_submission_configs_have_people_and_four_distinct_views():
    for name in ("submission-four.yaml", "submission-efficient.yaml"):
        data = AppConfig.model_validate(yaml.safe_load((Path("configs") / name).read_text()))
        assert len(data.cameras) == 4
        assert "cam05-crosswalk" in [camera.id for camera in data.cameras]
        assert len({camera.source.uri for camera in data.cameras}) == 4
        assert "person" in data.model.classes
        assert all(camera.line and camera.counting_region and camera.forbidden_zones
                   for camera in data.cameras)


def test_mosaic_letterboxes_instead_of_distorting_tall_people_view():
    frame = np.full((1100, 1200, 3), 127, np.uint8)
    result = tile(frame, "cam05-crosswalk")
    assert result.shape == (360, 640, 3)
    assert not result[100:, :120].any()
    assert (result[100:, 150:490] == 127).all()


def test_api_runner_handles_uvicorn_sigint_reraise(monkeypatch):
    from types import SimpleNamespace

    from scripts import serve

    def interrupted():
        raise KeyboardInterrupt

    monkeypatch.setattr("sys.argv", ["serve"])
    monkeypatch.setattr(serve.uvicorn, "Server", lambda _: SimpleNamespace(run=interrupted))
    serve.main()
