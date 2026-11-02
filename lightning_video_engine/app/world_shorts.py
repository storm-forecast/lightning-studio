"""Independent global rain Shorts for the TROVOX GLOB YouTube channel."""
import asyncio
import json
import math
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import urlopen

from PIL import Image, ImageDraw, ImageFont

from .world_alerts import alerts

FONT = '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'
BOLD = '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'


def candidates():
    """Only high rain, flood-potential, or severe-weather conditions publish automatically."""
    return [row for row in alerts() if row.get('nivel') == 'alta' and row.get('gatilhos') and not row.get('erro')]


def lightning_nowcast(lat, lon):
    """Observed satellite lightning where the Lightning Agent has coverage; never invent strikes."""
    base = os.environ.get('LIGHTNING_API_URL', 'https://lightning-agent.onrender.com').rstrip('/')
    try:
        with urlopen(base + '/alertas/situacao?' + urlencode({'lat': lat, 'lon': lon}), timeout=30) as response:
            value = json.load(response)
        return value if not value.get('dados_atrasados') else {'coberto': False, 'indisponivel': 'stale data'}
    except Exception:
        return {'coberto': False, 'indisponivel': 'source unavailable'}


def report(row):
    now = datetime.now(timezone.utc)
    city, country = row['cidade'], row['pais']
    current = row['chuva_atual_mm']
    probability = row['probabilidade_6h']
    triggers = row.get('gatilhos', [])
    lightning = lightning_nowcast(row['lat'], row['lon'])
    headline = ('Potential flooding' if 'potential_flooding' in triggers else
                'Severe weather potential' if 'severe_weather' in triggers else 'Heavy rain potential')
    severity = 'HIGH' if 'potential_flooding' in triggers or 'severe_weather' in triggers else 'ELEVATED'
    observed = ("Rain is currently affecting the city area." if current > 0
                else "No rain is measured at this point right now.")
    lightning_line = (f"Satellite lightning nowcasting reports {lightning.get('raios_40km', 0)} lightning strikes within 40 kilometres in the last 30 minutes. "
                      if lightning.get('coberto') else "Satellite lightning nowcasting is not available over this location. ")
    script = (f"{headline} in {city}, {country}. {observed} "
              f"The highest precipitation probability over the next six hours is {probability} percent. "
              + lightning_line + "This is an automated weather estimate, not an official warning. "
              "Follow your local weather service and emergency guidance. "
              "Subscribe to TROVOX GLOBAL for global weather updates.")
    return {'cidade': row['id'], 'nome': city, 'uf': country, 'pais': country,
            'verificado_em': now.isoformat().replace('+00:00', 'Z'), 'gerar': True,
            'motivos': triggers,
            'roteiro': script, 'recomendacoes': ['Check your local weather service.',
                                                  'Follow official emergency guidance.'],
            'timezone': row.get('timezone', 'UTC'), 'idioma': 'en-GB', 'fonte': 'Open-Meteo', 'oficial': False,
            'chuva_atual_mm': current, 'probabilidade_6h': probability, 'gatilhos': triggers, 'raios': lightning,
            'lat': row['lat'], 'lon': row['lon'],
            'titulo_short': f"{city}: {headline.lower()} #Shorts", 'headline': headline, 'severity': severity}


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
    draw.text((42, 50), 'TROVOX GLOBAL', font=ImageFont.truetype(BOLD, 31), fill='#60e5cf')
    draw.text((42, 112), item['headline'].upper(), font=ImageFont.truetype(BOLD, 20), fill='#ffbe61')
    draw.text((42, 178), item['nome'], font=bold, fill='white')
    draw.text((42, 238), item['pais'], font=regular, fill='#bed3e4')
    lat, lon = item['lat'], item['lon']
    span = .55
    lon_span = span / max(.25, math.cos(math.radians(lat)))
    region = basemap((lon - lon_span, lon + lon_span, lat - span, lat + span), directory.parent / 'map-tile-cache')
    image.paste(region, (40, 300))
    # This is a city-centred forecast signal, not a fabricated inundation polygon.
    overlay = Image.new('RGBA', (640, 600), (0, 0, 0, 0))
    risk = ImageDraw.Draw(overlay)
    colour = '#e9484a' if item['severity'] == 'HIGH' else '#f49a28'
    risk.ellipse((150, 110, 490, 450), fill=colour + '55', outline=colour + 'dd', width=5)
    image.paste(overlay, (40, 300), overlay)
    draw.rectangle((40, 300, 680, 900), outline='white', width=2)
    draw.ellipse((352, 592, 368, 608), fill='#ed3d3d', outline='white', width=2)
    draw.rounded_rectangle((38, 315, 350, 370), radius=10, fill='#081522cc')
    draw.text((55, 330), 'CITY-CENTRED RISK MAP', font=ImageFont.truetype(BOLD, 18), fill='white')
    draw.rounded_rectangle((38, 930, 682, 1175), radius=24, fill='#142b3e')
    draw.text((68, 954), f"SEVERITY: {item['severity']}", font=ImageFont.truetype(BOLD, 30), fill=colour)
    draw.text((68, 1008), item['headline'].upper(), font=ImageFont.truetype(BOLD, 27), fill='white')
    draw.text((68, 1054), 'Forecast / nowcast signal for the city area', font=ImageFont.truetype(FONT, 20), fill='#dceaf4')
    lightning = item.get('raios', {})
    lightning_text = (f"LIGHTNING NOWCAST: {lightning.get('raios_40km', 0)} strikes / 40 km / 30 min"
                      if lightning.get('coberto') else 'LIGHTNING NOWCAST: satellite coverage unavailable')
    draw.text((68, 1088), lightning_text, font=ImageFont.truetype(FONT, 18), fill='#dceaf4')
    draw.text((68, 1125), 'Subscribe to TROVOX GLOBAL for weather updates.', font=ImageFont.truetype(FONT, 20), fill='#dceaf4')
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
