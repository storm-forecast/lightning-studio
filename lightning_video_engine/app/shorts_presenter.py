"""Branded portrait composition and the Studio's per-narration Wav2Lip presenter."""
import os
import subprocess
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
from PIL import Image, ImageDraw, ImageFont
from .wardrobe import wardrobe_for_job

ROOT = Path(__file__).resolve().parents[2]
FONT = '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'
BOLD = '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'


def layout(image, report, title, kind):
    import textwrap
    canvas = Image.new('RGB', (720,1280), '#081522')
    d = ImageDraw.Draw(canvas)
    def text(value, x, y, size=24, color='white', bold=False, width=None):
        if report.get('idioma') == 'es-AR':
            from .shorts_spanish import screen_es
            value = screen_es(value)
        font = ImageFont.truetype(BOLD if bold else FONT,size)
        lines = textwrap.wrap(value,width) if width else [value]
        for line in lines:
            d.text((x,y),line,font=font,fill=color);y += size+9
        return y
    def card(box, fill='#142b3e'):
        d.rounded_rectangle(box, radius=18, fill=fill)
    d.rectangle((0,0,720,9),fill='#60e5cf')
    text('TROVOX TEMPO',32,30,27,'#60e5cf',True)
    text('ALERTA • NOWCASTING',32,82,20,'#ffbe61',True)
    text(f"{report['nome']} • {report['uf']}",32,122,38,bold=True)
    timezone = ZoneInfo(report.get('timezone','America/Sao_Paulo'))
    time = datetime.fromisoformat(report['verificado_em'].replace('Z','+00:00')).astimezone(timezone)
    text(time.strftime('%d/%m/%Y • %H:%M') + (' • Argentina (UTC−3)' if report.get('idioma') == 'es-AR' else ' • Brasília (UTC−3)'),32,181,20,'#bed3e4')
    text(title.upper(),32,233,22,bold=True)
    card((30,280,690,760))
    if kind != 'fim':
        tile=image.crop((40,400,680,1000)).resize((620,420),Image.Resampling.LANCZOS)
        canvas.paste(tile,(50,295))
        text('N ↑ • Amarelo: raios • Centro marcado' if kind == 'raios' else 'N ↑ • Risco: baixo / moderado / alto',50,725,18,'#bed3e4')
        d.rounded_rectangle((285,516,445,546),radius=5,fill='#081522')
        text(report['nome'],295,520,16,'white',True)
        text('© OpenStreetMap contributors',55,691,14,'#122535',True)
    else:
        text('PROTEJA-SE',55,305,29,'#60e5cf',True)
        y=365
        for i, value in enumerate(report['recomendacoes'],1):
            y=text(f'{i}. {value}',55,y,25,width=35)+20
    card((30,785,420,1195))
    text('PREVISÃO LOCAL',50,807,21,'#60e5cf',True)
    point=report.get('nowcasting') or {}
    y=text('Risco agora: ' + {'alta':'alto','moderada':'moderado','baixa':'baixo'}.get(point.get('risco'), 'indisponível'),50,852,23,bold=True,width=24)
    y=text('+30 min: ' + str(point.get('em_30_min','indisponível')),50,y+12,23,width=24)
    motion=point.get('deslocamento')
    if motion:
        y=text(f"Movimento: {motion['para']} • {motion['velocidade_kmh']} km/h",50,y+12,22,width=25)
    else:y=text('Movimento não determinado',50,y+12,22,width=25)
    count=report['raios'].get('raios_40km',0)
    text(f'{count} raios / 40 km / 30 min',50,y+16,20,'#ffbe61',width=27)
    text('APRESENTADORA IA',445,1175,16,'#bed3e4')
    text('Estimativa regional • acompanhe a Defesa Civil',32,1222,19,'#bed3e4')
    return canvas


def synchronize(directory):
    python=Path(os.environ.get('LIPSYNC_PYTHON',ROOT/'.local/venv/bin/python'))
    model=Path(os.environ.get('WAV2LIP_ROOT',ROOT/'.local/Wav2Lip'))
    checkpoint=Path(os.environ.get('WAV2LIP_CHECKPOINT',model/'checkpoints/wav2lip-compatible.pth'))
    if not python.is_file() or not checkpoint.is_file():
        raise RuntimeError('Short com apresentadora exige o ambiente Wav2Lip do Studio')
    presenter=wardrobe_for_job(directory)
    (directory/'apresentadora-origem.txt').write_text(presenter['file'])
    face=directory/'face.mp4';audio=directory/'narracao.wav';synced=directory/'apresentadora.mp4'
    subprocess.run(['ffmpeg','-y','-v','error','-i',presenter['file'],'-an','-vf',
                    "crop=w='if(gt(iw/ih,1),trunc(ih*0.72/2)*2,iw)':h=ih,scale=384:-2,fps=25",
                    '-threads','2',str(face)],check=True,timeout=120)
    subprocess.run(['ffmpeg','-y','-v','error','-i',str(directory/'voz.mp3'),'-ar','16000','-ac','1',str(audio)],check=True,timeout=120)
    subprocess.run([str(python),str(ROOT/'scripts/sync_presenter.py'),'--face',str(face),'--audio',str(audio),'--output',str(synced)],check=True,timeout=3600)
    return synced
