#!/usr/bin/env python3
"""Local Wav2Lip preview using fast, per-frame face tracking on CPU.

Input video must already have its final motion speed and input audio its final
speech speed. Do not change either speed after synchronizing the lips.
The installed Wav2Lip research model retains its own licensing restrictions.
"""
import argparse
from pathlib import Path
import os
import runpy
import shutil
import sys
import tempfile

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--face', type=Path, required=True)
parser.add_argument('--audio', type=Path, required=True)
parser.add_argument('--output', type=Path, required=True)
args = parser.parse_args()
root = Path(__file__).resolve().parents[1]
model_root = Path(os.environ.get('WAV2LIP_ROOT', str(root / '.local/Wav2Lip')))
checkpoint = Path(os.environ.get('WAV2LIP_CHECKPOINT', str(model_root / 'checkpoints/wav2lip-compatible.pth')))
for file in (args.face, args.audio, checkpoint):
    if not file.is_file():
        raise FileNotFoundError(file)
face, audio, output = args.face.resolve(), args.audio.resolve(), args.output.resolve()
os.environ['CUDA_VISIBLE_DEVICES'] = ''
os.environ['OMP_NUM_THREADS'] = '2'
os.environ['MKL_NUM_THREADS'] = '2'
import cv2
import torch
import numpy as np

torch.set_num_threads(2)
cv2.setNumThreads(1)
detector = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_frontalface_default.xml')


def track_faces(frames):
    results = []
    previous = None
    for frame in frames:
        boxes = detector.detectMultiScale(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), 1.1, 5)
        if len(boxes):
            x, y, width, height = max(boxes, key=lambda b: b[2] * b[3])
            previous = (max(0, y-5), min(frame.shape[0], y+height+12),
                        max(0, x-5), min(frame.shape[1], x+width+5))
        if previous is None:
            raise RuntimeError('rosto não encontrado no primeiro quadro')
        y1, y2, x1, x2 = previous
        results.append([frame[y1:y2, x1:x2], (y1, y2, x1, x2)])
    return results


# Upstream uses fixed relative temp paths and a shell for the final mux.
# Isolate each run and use simple file names there.
with tempfile.TemporaryDirectory(prefix='lipsync-') as temp:
    shutil.copy2(face, Path(temp) / 'face.mp4')
    shutil.copy2(audio, Path(temp) / 'audio.wav')
    old_cwd = Path.cwd()
    try:
        os.chdir(temp)
        Path('temp').mkdir()
        sys.path.insert(0, str(model_root))
        sys.argv = ['inference.py', '--checkpoint_path', str(checkpoint),
                    '--face', 'face.mp4', '--audio', 'audio.wav',
                    '--outfile', 'synced.mp4', '--wav2lip_batch_size', '8']
        module = runpy.run_path(str(model_root / 'inference.py'), run_name='local_inference')
        main = module['main']
        main.__globals__['face_detect'] = track_faces
        main()
        output.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2('synced.mp4', output)
    finally:
        os.chdir(old_cwd)
print(output)
