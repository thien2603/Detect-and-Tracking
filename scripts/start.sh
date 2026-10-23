#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
export CONFIG_PATH="${CONFIG_PATH:-configs/config.yaml}"
exec python -m uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
