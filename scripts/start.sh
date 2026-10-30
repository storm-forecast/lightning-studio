#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
if [ -n "${LIPSYNC_PYTHON:-}" ]; then
  PYTHON="$LIPSYNC_PYTHON"
elif [ -x .local/venv/bin/python ]; then
  PYTHON="$PWD/.local/venv/bin/python"
else
  PYTHON="$(command -v python)"
fi
"$PYTHON" scripts/bootstrap_runtime.py
exec "$PYTHON" -m uvicorn lightning_video_engine.app.main:app --host 0.0.0.0 --port "${PORT:-10000}" --workers 1
