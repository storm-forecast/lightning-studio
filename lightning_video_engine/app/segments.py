"""Scene contract and measured audio timeline for meteorological bulletins."""
from dataclasses import asdict, dataclass, field
from pathlib import Path
import json
import math
import wave

@dataclass
class Segment:
    id: str
    title: str
    category: str
    view: str
    source: str = 'ecens'
    place: dict | None = None
    horizon: int | None = None
    narration: str = ''
    image: str = ''
    audio: str = ''
    available: bool = True
    metadata: dict = field(default_factory=dict)
    evidence: dict = field(default_factory=dict)
    duration: float = 0
    start: float = 0
    end: float = 0


def save_plan(segments, destination):
    Path(destination).write_text(json.dumps([asdict(s) for s in segments], ensure_ascii=False, indent=2)+'\n')


def join_audio(segments: list[Segment], destination: Path):
    """Align each final 16kHz PCM segment to a video frame and record exact cuts."""
    elapsed_samples = 0
    with wave.open(str(destination), 'wb') as out:
        out.setparams((1, 2, 16000, 0, 'NONE', 'not compressed'))
        for s in segments:
            with wave.open(s.audio, 'rb') as audio:
                if (audio.getnchannels(), audio.getsampwidth(), audio.getframerate()) != (1,2,16000):
                    raise ValueError('o áudio final por cena deve ser PCM mono 16kHz/16bit')
                samples = audio.getnframes()
                frames = math.ceil(samples/640)  # 16000 samples/s / 25 video frames/s
                padded = frames*640
                data = audio.readframes(samples) + b'\x00\x00'*(padded-samples)
            s.start = elapsed_samples/16000
            s.duration = padded/16000
            elapsed_samples += padded
            s.end = elapsed_samples/16000
            out.writeframesraw(data)
    return elapsed_samples/16000
