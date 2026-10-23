.PHONY: install test lint model video render serve
install:
	python -m pip install -e '.[inference,dev]'
test:
	python -m pytest
lint:
	python -m ruff check app scripts tests benchmarks
model:
	python -m scripts.download_model
video:
	python -m scripts.download_expressway
render:
	python -m scripts.render_video
serve:
	python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
