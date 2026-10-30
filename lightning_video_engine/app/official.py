"""Approved bulletin pipeline: final timing, lip sync, then music and maps."""
from pathlib import Path
import os
import subprocess
import tempfile

from .broadcast import compose
from .wardrobe import wardrobe_for_job

ROOT = Path(__file__).resolve().parents[2]


def render_official(scenes, audio, destination, *, title, subtitle,
                    ffmpeg='ffmpeg', ffprobe='ffprobe', scene_durations=None, narration_final=False, presenter_source=None):
    presenter_source = presenter_source or Path(wardrobe_for_job(Path(destination).parent)['file'])
    python = Path(os.environ.get('LIPSYNC_PYTHON', str(ROOT / '.local/venv/bin/python')))
    model_root = Path(os.environ.get('WAV2LIP_ROOT', str(ROOT / '.local/Wav2Lip')))
    checkpoint = Path(os.environ.get('WAV2LIP_CHECKPOINT', str(model_root / 'checkpoints/wav2lip-compatible.pth')))
    if not python.is_file() or not checkpoint.is_file():
        raise RuntimeError('Template oficial exige sincronização labial local: instale '
                           '.local/venv e .local/Wav2Lip com checkpoint compatível; '
                           'o Docker básico não inclui esse ambiente/modelo')
    with tempfile.TemporaryDirectory(prefix='official-') as folder:
        face, speech, synced = (Path(folder) / name for name in ('face.mp4', 'speech.wav', 'synced.mp4'))
        speed = float(os.environ.get('PRESENTER_SPEED', '1.0'))
        rate = float(os.environ.get('NARRATION_SPEED', '0.90'))
        if narration_final:
            rate = 1.0
        if not (0.5 <= speed <= 2 and 0.5 <= rate <= 2):
            raise ValueError('velocidades devem estar entre 0.5 e 2.0')
        subprocess.run([ffmpeg, '-y', '-v', 'error', '-i', str(presenter_source),
                        '-an', '-vf', f"setpts=(PTS-STARTPTS)/{speed},"
                        "crop=w='if(gt(iw/ih,1),trunc(ih*0.72/2)*2,iw)':h=ih,scale=384:-2,fps=25",
                        '-threads', '2', str(face)], check=True, timeout=120)
        subprocess.run([ffmpeg, '-y', '-v', 'error', '-i', str(audio), '-af', f'atempo={rate}',
                        '-ar', '16000', '-ac', '1', str(speech)], check=True, timeout=120)
        subprocess.run([str(python), str(ROOT / 'scripts/sync_presenter.py'),
                        '--face', str(face), '--audio', str(speech), '--output', str(synced)],
                       check=True, timeout=3600)
        compose(scenes, speech, destination, title=title, subtitle=subtitle,
                presenter=synced, timing_final=True, ffmpeg=ffmpeg, ffprobe=ffprobe,
                scene_durations=scene_durations)
