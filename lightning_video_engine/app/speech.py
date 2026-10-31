"""Brazilian female narration through Edge's online TTS; no silent voice fallback."""
from pathlib import Path
import os
import subprocess
import sys
import tempfile


def narrate(text: str, destination: Path, *, ffmpeg: str = 'ffmpeg') -> None:
    if not text.strip():
        raise ValueError('roteiro vazio')
    voice = os.environ.get('EDGE_TTS_VOICE', 'pt-BR-FranciscaNeural')
    if voice != 'pt-BR-FranciscaNeural':
        raise ValueError('a voz feminina brasileira configurada é pt-BR-FranciscaNeural')
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='narration-') as folder:
        script = Path(folder) / 'script.txt'
        mp3 = Path(folder) / 'speech.mp3'
        script.write_text(text, encoding='utf-8')
        subprocess.run([sys.executable, '-m', 'edge_tts', '--voice', voice,
                        '--rate=-5%', '--file', str(script), '--write-media', str(mp3)],
                       check=True, timeout=180)
        subprocess.run([ffmpeg, '-y', '-v', 'error', '-i', str(mp3), '-ar', '48000',
                        '-ac', '1', str(destination)], check=True, timeout=60)


def prepare_scene_audio(scene, directory):
    """Reuse only verified text/voice/rate audio; publish files after successful conversion."""
    import hashlib
    import math
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    rate = float(os.environ.get('NARRATION_SPEED', '0.90'))
    if not math.isfinite(rate) or not 0.5 <= rate <= 2:
        raise ValueError('velocidade de narração deve estar entre 0.5 e 2.0')
    voice = os.environ.get('EDGE_TTS_VOICE', 'pt-BR-FranciscaNeural')
    raw_key = hashlib.sha256((scene.narration + '\0' + voice + '\0edge-rate=-5%').encode()).hexdigest()
    final_key = hashlib.sha256((raw_key + '\0' + str(rate)).encode()).hexdigest()
    raw = directory / f'{scene.id}-raw.wav'
    final = directory / f'{scene.id}.wav'
    raw_cache = directory / f'{scene.id}-raw.sha256'
    cache = directory / f'{scene.id}.sha256'
    raw_valid = raw.is_file() and raw_cache.is_file() and raw_cache.read_text() == raw_key
    final_valid = final.is_file() and cache.is_file() and cache.read_text() == final_key
    if final_valid:
        return str(final)
    with tempfile.TemporaryDirectory(prefix=f'{scene.id}-', dir=directory) as folder:
        temporary = Path(folder)
        if not raw_valid:
            candidate = temporary / 'raw.wav'
            narrate(scene.narration, candidate)
            candidate.replace(raw)
            raw_cache.write_text(raw_key)
        candidate = temporary / 'final.wav'
        subprocess.run(['ffmpeg', '-y', '-v', 'error', '-i', str(raw),
                        '-af', f'atempo={rate}', '-ar', '16000', '-ac', '1',
                        '-threads', '1', str(candidate)], check=True)
        candidate.replace(final)
        cache.write_text(final_key)
    return str(final)


def prepare_scene_audios(scenes, directory, workers=2):
    """Bounded TTS concurrency; scene order is retained by the caller's list."""
    from concurrent.futures import ThreadPoolExecutor, as_completed
    if not 1 <= workers <= 4:
        raise ValueError('VIDEO_TTS_WORKERS deve estar entre 1 e 4')
    with ThreadPoolExecutor(max_workers=workers) as pool:
        pending = {pool.submit(prepare_scene_audio, scene, directory): scene for scene in scenes}
        for future in as_completed(pending):
            scene = pending[future]
            scene.audio = future.result()
            print('Áudio pronto:', scene.id, flush=True)
