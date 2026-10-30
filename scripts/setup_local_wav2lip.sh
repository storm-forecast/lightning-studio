#!/usr/bin/env bash
# Installs only free, local dependencies. The model checkpoint must be obtained from Wav2Lip's official release.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TARGET="$ROOT/.local/Wav2Lip"
mkdir -p "$ROOT/.local"
if [ ! -d "$TARGET/.git" ]; then git clone https://github.com/Rudrabha/Wav2Lip.git "$TARGET"; fi
python3 -m venv "$ROOT/.local/venv"
"$ROOT/.local/venv/bin/pip" install --upgrade pip setuptools wheel
# The repository pins NumPy 1.17, which cannot build on Python 3.11.  These
# compatible CPU wheels preserve the inference API used by inference.py.
"$ROOT/.local/venv/bin/pip" install \
  'numpy>=1.23,<2' 'librosa>=0.9,<0.11' 'scipy>=1.9' 'opencv-python>=4.7' \
  'torch>=2.0' 'torchvision>=0.15' 'tqdm' 'numba' 'face-alignment>=1.3' 'gdown'
echo "Baixe o checkpoint oficial wav2lip_gan.pth e salve em: $TARGET/checkpoints/wav2lip_gan.pth"
