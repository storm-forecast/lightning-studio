#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
python3 -m venv .local/venv
PYTHON="$ROOT/.local/venv/bin/python"
"$PYTHON" -m pip install --upgrade pip
"$PYTHON" -m pip install --index-url https://download.pytorch.org/whl/cpu 'torch==2.6.0'
"$PYTHON" -m pip install -r requirements.txt -r requirements-lipsync.txt
"$PYTHON" scripts/bootstrap_runtime.py "$@"
