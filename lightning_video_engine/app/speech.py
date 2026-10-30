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
