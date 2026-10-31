"""Reusable 1080p bulletin layout. Weather imagery is never cropped or stretched."""
from __future__ import annotations

import os
import math
from pathlib import Path
import subprocess
import tempfile
import textwrap


def compose(scenes: list[Path], audio: Path, destination: Path, *, title: str,
            subtitle: str, presenter: Path | None = None,
            ffmpeg: str = 'ffmpeg', ffprobe: str = 'ffprobe', timing_final: bool = False, scene_durations: list[float] | None = None) -> None:
    presenter_speed = float(os.environ.get('PRESENTER_SPEED', '1.0'))
    narration_speed = float(os.environ.get('NARRATION_SPEED', '0.90'))
    if timing_final:
        presenter_speed = narration_speed = 1.0
    if not all(math.isfinite(value) and 0.5 <= value <= 2.0
               for value in (presenter_speed, narration_speed)):
        raise ValueError('velocidades devem estar entre 0.5 e 2.0')
    if not scenes:
        raise ValueError('nenhuma cena disponível')
    for source in [*scenes, audio, *([presenter] if presenter else [])]:
        if not source.is_file():
            raise FileNotFoundError(source)
    duration = float(subprocess.check_output([
        ffprobe, '-v', 'error', '-show_entries', 'format=duration',
        '-of', 'default=noprint_wrappers=1:nokey=1', str(audio)]))
    if duration <= 0:
        raise ValueError('áudio sem duração válida')
    duration /= narration_speed
    destination.parent.mkdir(parents=True, exist_ok=True)
    # Two encoder threads limit contention on the host. No inference runs here.
    cmd = [ffmpeg, '-y', '-v', 'warning', '-filter_complex_threads', '1']
    durations = scene_durations or [duration / len(scenes)] * len(scenes)
    if len(durations) != len(scenes) or any(not math.isfinite(d) or d <= 0 for d in durations):
        raise ValueError('duração inválida para as cenas')
    if abs(sum(durations)-duration) > 0.08:
        raise ValueError('a linha do tempo das imagens não coincide com o áudio')
    for source, seconds in zip(scenes, durations):
        cmd += ['-loop', '1', '-framerate', '25', '-t', f'{seconds:.6f}', '-i', str(source)]
    audio_index = len(scenes)
    cmd += ['-i', str(audio)]
    if presenter:
        cmd += ['-stream_loop', '-1', '-i', str(presenter)]
    configured_music = os.environ.get('BACKGROUND_MUSIC', '')
    music = Path(configured_music) if configured_music else Path(__file__).resolve().parents[2] / 'templates/fundo-musical.wav'
    if configured_music and not music.is_file():
        raise FileNotFoundError(music)
    music_index = audio_index + 1 + int(presenter is not None)
    if music.is_file():
        cmd += ['-stream_loop', '-1', '-i', str(music)]
    width = 1440 if presenter else 1856
    with tempfile.TemporaryDirectory(prefix='broadcast-') as temp:
        graph = [f'[{audio_index}:a:0]atempo={narration_speed}[narration]']
        audio_label = '[narration]'
        if music.is_file():
            graph += [
                '[narration]aresample=48000,asplit=2[voice][key]',
                f'[{music_index}:a:0]aresample=48000,volume=0.25,'
                f'afade=t=in:d=0.6,afade=t=out:st={max(0, duration-1.5):.3f}:d=1.5[music]',
                '[music][key]sidechaincompress=threshold=0.025:ratio=8:attack=20:release=350[ducked]',
                '[voice][ducked]amix=inputs=2:duration=first:normalize=0,alimiter=limit=0.95:latency=1[mixed]',
            ]
            audio_label = '[mixed]'
        for i in range(len(scenes)):
            graph.append(f'[{i}:v]scale={width}:810:force_original_aspect_ratio=decrease,'
                         f'pad={width}:810:(ow-iw)/2:(oh-ih)/2:color=0x101e30,'
                         f'fps=25,setsar=1,format=yuv420p,trim=duration={durations[i]:.6f},setpts=PTS-STARTPTS[s{i}]')
        graph.append(''.join(f'[s{i}]' for i in range(len(scenes))) +
                     f'concat=n={len(scenes)}:v=1:a=0[maps]')
        graph.append(f'color=c=0x091422:s=1920x1080:r=25:d={duration:.6f}[bg]')
        graph.append('[bg][maps]overlay=32:144:shortest=1[base]')
        base = 'base'
        if presenter:
            graph.append(f"[{audio_index+1}:v]setpts=(PTS-STARTPTS)/{presenter_speed},fps=25,crop=w='if(gt(iw/ih,1),trunc(ih*0.72/2)*2,iw)':h=ih,"
                         'scale=384:810:force_original_aspect_ratio=decrease,'
                         'pad=384:810:(ow-iw)/2:(oh-ih)/2:color=0x101e30,setsar=1[p]')
            graph.append('[base][p]overlay=1504:144:shortest=1[withpresenter]')
            base = 'withpresenter'
        labels = [
            ('TROVOX TEMPO', 32, 25, 25, '0x65e0d0'),
            (textwrap.shorten(title, width=64, placeholder='…'), 32, 65, 36, 'white'),
            (textwrap.shorten(subtitle, width=110, placeholder='…'), 32, 985, 24, 'white'),
            ('Mapas e legendas: TROVOX TEMPO | Apresentação virtual', 32, 1030, 20, '0xb9c8d9'),
        ]
        if presenter:
            labels.append(('APRESENTAÇÃO VIRTUAL', 1504, 100, 19, '0xb9c8d9'))
        filters = ['drawbox=x=32:y=126:w=1856:h=3:color=0x65e0d0:t=fill',
                   'drawbox=x=32:y=970:w=1856:h=2:color=0x30445a:t=fill']
        font = Path(os.environ.get('VIDEO_FONT', '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'))
        if not font.is_file():
            raise RuntimeError('fonte ausente: configure VIDEO_FONT')
        # Text files keep titles out of FFmpeg filter syntax and disable expansion.
        for i, (label, x, y, size, color) in enumerate(labels):
            file = Path(temp) / f'label-{i}.txt'
            file.write_text(label.replace('\n', ' '), encoding='utf-8')
            filters.append(f"drawtext=fontfile='{font}':textfile='{file}':expansion=none:"
                           f'x={x}:y={y}:fontsize={size}:fontcolor={color}')
        graph.append(f'[{base}]' + ','.join(filters) + '[out]')
        cmd += ['-filter_complex', ';'.join(graph), '-map', '[out]', '-map', audio_label,
                '-t', f'{duration:.6f}', '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '21',
                '-maxrate', '5M', '-bufsize', '10M', '-threads', '2', '-pix_fmt', 'yuv420p',
                '-c:a', 'aac', '-b:a', '128k', '-ar', '48000', '-movflags', '+faststart', str(destination)]
        subprocess.run(cmd, check=True, timeout=max(300, int(duration * 10)))
