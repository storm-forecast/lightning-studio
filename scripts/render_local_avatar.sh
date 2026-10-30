#!/usr/bin/env bash
# Free local talking-presenter render. Wav2Lip uses CUDA when available and CPU otherwise.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
WAV2LIP_ROOT="${WAV2LIP_ROOT:-$ROOT/.local/Wav2Lip}"
CHECKPOINT="${WAV2LIP_CHECKPOINT:-$WAV2LIP_ROOT/checkpoints/wav2lip_gan.pth}"
AVATAR="${1:-$ROOT/assets-presenter.png}"
AUDIO="${2:-$ROOT/output/boletim-regional.wav}"
MAP_VIDEO="${3:-$ROOT/output/boletim-regional.mp4}"
OUTPUT="${4:-$ROOT/output/boletim-com-apresentadora-animada.mp4}"
VAAPI_DEVICE="${VAAPI_DEVICE:-/dev/dri/renderD128}"

test -d "$WAV2LIP_ROOT" || { echo "Wav2Lip ausente: execute scripts/setup_local_wav2lip.sh" >&2; exit 1; }
test -f "$CHECKPOINT" || { echo "Checkpoint ausente: $CHECKPOINT" >&2; exit 1; }
test -f "$AVATAR" && test -f "$AUDIO" && test -f "$MAP_VIDEO"

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
# Wav2Lip's OpenCV writer is unreliable when the face input is a single PNG.
# Give it a real, silent video stream lasting longer than the narration instead.
ffmpeg -y -loop 1 -i "$AVATAR" -i "$AUDIO" -c:v libx264 -tune stillimage -c:a aac -pix_fmt yuv420p -shortest "$TMP/face.mp4"
"$ROOT/.local/venv/bin/python" "$WAV2LIP_ROOT/inference.py" --checkpoint_path "$CHECKPOINT" --face "$TMP/face.mp4" --audio "$AUDIO" --outfile "$TMP/avatar.mp4"
test -s "$TMP/avatar.mp4" || { echo "Wav2Lip não gerou o vídeo do avatar" >&2; exit 1; }
# Map at left; animated presenter at right. This avoids pretending an opaque image is transparent.
if [ -r "$VAAPI_DEVICE" ] && [ -w "$VAAPI_DEVICE" ]; then
  # Intel GPU accelerates only final H.264 encoding; Wav2Lip inference remains CPU-bound.
  if ffmpeg -y -vaapi_device "$VAAPI_DEVICE" -stream_loop -1 -i "$MAP_VIDEO" -i "$TMP/avatar.mp4" \
    -filter_complex '[0:v]scale=1280:720[map];[1:v]scale=-2:720[p];[map][p]hstack=inputs=2,format=nv12,hwupload[v]' \
    -map '[v]' -map 1:a -c:v h264_vaapi -c:a aac -shortest "$OUTPUT"; then
    exit 0
  fi
  echo "VAAPI indisponível; exportando por CPU." >&2
  rm -f "$OUTPUT"
  ffmpeg -y -stream_loop -1 -i "$MAP_VIDEO" -i "$TMP/avatar.mp4" \
    -filter_complex '[0:v]scale=1280:720[map];[1:v]scale=-2:720[p];[map][p]hstack=inputs=2[v]' \
    -map '[v]' -map 1:a -c:v libx264 -preset veryfast -c:a aac -pix_fmt yuv420p -shortest "$OUTPUT"
else
  ffmpeg -y -stream_loop -1 -i "$MAP_VIDEO" -i "$TMP/avatar.mp4" \
    -filter_complex '[0:v]scale=1280:720[map];[1:v]scale=-2:720[p];[map][p]hstack=inputs=2[v]' \
    -map '[v]' -map 1:a -c:v libx264 -preset veryfast -c:a aac -pix_fmt yuv420p -shortest "$OUTPUT"
fi
echo "$OUTPUT"
