"""Independent global rain Shorts for the TROVOX GLOB YouTube channel."""
import asyncio
import json
import math
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .world_alerts import alerts

FONT = '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'
BOLD = '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'


def candidates():
    """Only high rain conditions produce automatic global videos."""
    return [row for row in alerts() if row.get('nivel') == 'alta' and not row.get('erro')]


def report(row):
    now = datetime.now(timezone.utc)
    city, country = row['cidade'], row['pais']
    current = row['chuva_atual_mm']
    probability = row['probabilidade_6h']
    observed = (f"Rain is currently observed at {current:.1f} millimetres." if current > 0
                else "No rain is measured at this point right now.")
    script = (f"Global rain update for {city}, {country}. {observed} "
              f"The highest precipitation probability over the next six hours is {probability} percent. "
              "This is an automated weather estimate, not an official warning. "
              "Follow your local weather service and emergency guidance. "
              "Subscribe to TROVOX GLOB for global weather updates.")
    return {'cidade': row['id'], 'nome': city, 'uf': country, 'pais': country,
            'verificado_em': now.isoformat().replace('+00:00', 'Z'), 'gerar': True,
            'motivos': ['high rain condition or elevated six-hour precipitation probability'],
            'roteiro': script, 'recomendacoes': ['Check your local weather service.',
                                                  'Follow official emergency guidance.'],
            'timezone': row.get('timezone', 'UTC'), 'idioma': 'en-GB', 'fonte': 'Open-Meteo', 'oficial': False,
            'chuva_atual_mm': current, 'probabilidade_6h': probability,
            'lat': row['lat'], 'lon': row['lon'],
            'titulo_short': f"{city}: rain and forecast for the next few hours #Shorts"}


def render(directory: Path, item):
    """Render a British-English map Short with the same presenter pipeline as TROVOX TEMPO."""
    import edge_tts
    from .regional_map import basemap
    from .shorts_presenter import synchronize

    directory.mkdir(parents=True, exist_ok=True)
    (directory / 'alerta.json').write_text(json.dumps(item, ensure_ascii=False, indent=2))
    asyncio.run(edge_tts.Communicate(item['roteiro'], 'en-GB-SoniaNeural').save(str(directory / 'voz.mp3')))
    image = Image.new('RGB', (720, 1280), '#081522')
    draw = ImageDraw.Draw(image)
    regular, bold = ImageFont.truetype(FONT, 30), ImageFont.truetype(BOLD, 48)
    draw.rectangle((0, 0, 720, 12), fill='#60e5cf')
    draw.text((42, 50), 'TROVOX GLOB', font=ImageFont.truetype(BOLD, 31), fill='#60e5cf')
    draw.text((42, 112), 'GLOBAL RAIN NOWCASTING', font=ImageFont.truetype(BOLD, 20), fill='#ffbe61')
    draw.text((42, 178), item['nome'], font=bold, fill='white')
    draw.text((42, 238), item['pais'], font=regular, fill='#bed3e4')
    lat, lon = item['lat'], item['lon']
    span = .55
    lon_span = span / max(.25, math.cos(math.radians(lat)))
    region = basemap((lon - lon_span, lon + lon_span, lat - span, lat + span), directory.parent / 'map-tile-cache')
    image.paste(region, (40, 300))
    draw.rectangle((40, 300, 680, 900), outline='white', width=2)
    draw.ellipse((352, 592, 368, 608), fill='#ed3d3d', outline='white', width=2)
    draw.rounded_rectangle((38, 930, 682, 1175), radius=24, fill='#142b3e')
    draw.text((68, 954), f"RAIN NOW: {item['chuva_atual_mm']:.1f} mm", font=ImageFont.truetype(BOLD, 30), fill='#60e5cf')
    draw.text((68, 1008), f"6-HOUR RAIN CHANCE: {item['probabilidade_6h']}%", font=ImageFont.truetype(BOLD, 27), fill='white')
    draw.text((68, 1060), 'Subscribe to TROVOX GLOB for weather updates.', font=ImageFont.truetype(FONT, 22), fill='#dceaf4')
    draw.text((42, 1210), 'Source: Open-Meteo • Not an official warning', font=ImageFont.truetype(FONT, 18), fill='#bed3e4')
    image.save(directory / 'card.png')
    duration = float(subprocess.check_output(['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', str(directory / 'voz.mp3')]))
    if duration > 60:
        raise ValueError('narration exceeds 60 seconds; Short not published')
    presenter = synchronize(directory)
    subprocess.run(['ffmpeg', '-y', '-v', 'error', '-loop', '1', '-i', str(directory / 'card.png'),
                    '-i', str(directory / 'voz.mp3'), '-i', str(presenter), '-filter_complex',
                    '[0:v]fps=25,setpts=PTS-STARTPTS[bg];[2:v]crop=trunc(iw*0.70/2)*2:trunc(ih*0.62/2)*2:(iw-ow)/2:ih*0.06,scale=240:360:force_original_aspect_ratio=increase,crop=240:360,setsar=1,fps=25,setpts=PTS-STARTPTS[p];[bg][p]overlay=445:805:shortest=1[v]',
                    '-map', '[v]', '-map', '1:a', '-c:v', 'libx264', '-threads', '2', '-pix_fmt', 'yuv420p',
                    '-r', '25', '-c:a', 'aac', '-shortest', str(directory / 'short.mp4')], check=True, timeout=300)
