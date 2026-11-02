"""Independent global rain Shorts for the TROVOX GLOB YouTube channel."""
import asyncio
import io
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


def lightning_points(bounds):
    """Recent observed strikes inside the displayed map bounds, for a factual nowcast layer."""
    base = os.environ.get('LIGHTNING_API_URL', 'https://lightning-agent.onrender.com').rstrip('/')
    west, east, south, north = bounds
    try:
        with urlopen(base + '/observado/mapa', timeout=45) as response:
            payload = json.load(response)
        return [(lat, lon) for lat, lon, _count, _unforecast, age in payload.get('pontos', [])
                if age * payload.get('idade_passo_min', 10) < 30 and south <= lat <= north and west <= lon <= east]
    except Exception:
        return []


def severity_overlay(bounds, size):
    """Crop the real Lightning Agent severity raster to the local Short map."""
    base = os.environ.get('LIGHTNING_API_URL', 'https://lightning-agent.onrender.com').rstrip('/')
    west, east, south, north = bounds
    try:
        with urlopen(base + '/previsao/agora', timeout=30) as response:
            meta = json.load(response)
        with urlopen(base + '/previsao/agora.png', timeout=60) as response:
            source = Image.open(io.BytesIO(response.read())).convert('RGBA')
        (south_map, west_map), (north_map, east_map) = meta['limites']
        def mercator_value(value):
            return math.log(math.tan(math.pi / 4 + math.radians(value) / 2))
        x0, x1 = ((west - west_map) / (east_map - west_map) * source.width,
                  (east - west_map) / (east_map - west_map) * source.width)
        y0 = (mercator_value(north_map) - mercator_value(north)) / (mercator_value(north_map) - mercator_value(south_map)) * source.height
        y1 = (mercator_value(north_map) - mercator_value(south)) / (mercator_value(north_map) - mercator_value(south_map)) * source.height
        crop = source.crop((int(x0), int(y0), int(x1) + 1, int(y1) + 1)).resize(size, Image.Resampling.LANCZOS)
        crop.putalpha(crop.getchannel('A').point(lambda alpha: int(alpha * .60)))
        return crop
    except Exception:
        return None


def report(row):
    now = datetime.now(timezone.utc)
    city, country = row['cidade'], row['pais']
    current = row.get('chuva_atual_mm', 0)
    probability = row.get('probabilidade_6h', 0)
    triggers = row.get('gatilhos', [])
    lightning = lightning_nowcast(row['lat'], row['lon'])
    official_event = row.get('evento_oficial')
    headline = (f'Official {official_event}' if official_event else
                'Potential flooding' if 'potential_flooding' in triggers else
                'Severe weather potential' if 'severe_weather' in triggers else 'Heavy rain potential')
    severity = 'HIGH' if 'potential_flooding' in triggers or 'severe_weather' in triggers or official_event else 'ELEVATED'
    observed = ("Rain is currently affecting the city area." if current > 0
                else "No rain is measured at this point right now.")
    if official_event:
        observed = f"The National Weather Service has issued this alert for {row.get('areas_afetadas', 'the affected area')}. "
    lightning_line = (f"Satellite lightning nowcasting reports {lightning.get('raios_40km', 0)} lightning strikes within 40 kilometres in the last 30 minutes. "
                      if lightning.get('coberto') else "Satellite lightning nowcasting is not available over this location. ")
    forecast_line = '' if official_event else f"The highest precipitation probability over the next six hours is {probability} percent. "
    advisory_line = (f"Follow the official instruction: {row.get('instrucao_oficial', '')} " if official_event
                     else "This is an automated weather estimate, not an official warning. ")
    script = (f"Nowcasting update: {headline} in {city}, {country}. {observed} " + forecast_line
              + lightning_line + advisory_line + "Follow your local weather service and emergency guidance. "
              + "Subscribe to TROVOX GLOBAL for global weather updates.")
    return {'cidade': row['id'], 'nome': city, 'uf': country, 'pais': country,
            'verificado_em': now.isoformat().replace('+00:00', 'Z'), 'gerar': True,
            'motivos': triggers,
            'roteiro': script, 'recomendacoes': ['Check your local weather service.',
                                                  'Follow official emergency guidance.'],
            'timezone': row.get('timezone', 'UTC'), 'idioma': 'en-GB',
            'chuva_atual_mm': current, 'probabilidade_6h': probability, 'gatilhos': triggers, 'raios': lightning,
            'oficial': bool(official_event), 'fonte': row.get('fonte', 'Open-Meteo'),
            'lat': row['lat'], 'lon': row['lon'],
            'geometria_alerta': row.get('geometria_alerta'),
            'titulo_short': f"{city}: {headline.lower()} #Shorts", 'headline': headline, 'severity': severity}


def render(directory: Path, item):
    """Render a British-English map Short with the same presenter pipeline as TROVOX TEMPO."""
    import edge_tts
    from .regional_map import basemap, mercator
    from .shorts_presenter import synchronize

    directory.mkdir(parents=True, exist_ok=True)
    (directory / 'alerta.json').write_text(json.dumps(item, ensure_ascii=False, indent=2))
    asyncio.run(edge_tts.Communicate(item['roteiro'], 'en-GB-SoniaNeural').save(str(directory / 'voz.mp3')))
    image = Image.new('RGB', (720, 1280), '#081522')
    draw = ImageDraw.Draw(image)
    regular, bold = ImageFont.truetype(FONT, 30), ImageFont.truetype(BOLD, 48)
    draw.rectangle((0, 0, 720, 12), fill='#60e5cf')
    draw.text((42, 50), 'TROVOX GLOBAL', font=ImageFont.truetype(BOLD, 31), fill='#60e5cf')
    draw.text((42, 112), 'GLOBAL NOWCASTING', font=ImageFont.truetype(BOLD, 20), fill='#ffbe61')
    draw.text((42, 178), item['nome'], font=bold, fill='white')
    draw.text((42, 238), item['pais'], font=regular, fill='#bed3e4')
    lat, lon = item['lat'], item['lon']
    geometry = item.get('geometria_alerta') or {}
    rings = (geometry.get('coordinates') or [])
    if geometry.get('type') == 'Polygon':
        rings = [rings]
    points = [point for ring_set in rings for ring in ring_set for point in ring]
    if points:
        west, east = min(point[0] for point in points), max(point[0] for point in points)
        south, north = min(point[1] for point in points), max(point[1] for point in points)
        pad = .08
        west, east, south, north = west - pad, east + pad, south - pad, north + pad
    else:
        span = .55
        lon_span = span / max(.25, math.cos(math.radians(lat)))
        west, east, south, north = lon - lon_span, lon + lon_span, lat - span, lat + span
    bounds = (west, east, south, north)
    # Same visual hierarchy as TROVOX TEMPO: map above, clear caption and
    # information panel left, presenter anchored in the lower-right corner.
    map_left, map_top, map_width, map_height = 40, 295, 640, 420
    region = basemap(bounds, directory.parent / 'map-tile-cache', size=(map_width, map_height))
    image.paste(region, (map_left, map_top))
    severity = severity_overlay(bounds, (map_width, map_height))
    if severity is not None:
        image.paste(severity, (map_left, map_top), severity)
    overlay = Image.new('RGBA', (map_width, map_height), (0, 0, 0, 0))
    risk = ImageDraw.Draw(overlay)
    colour = '#e9484a' if item['severity'] == 'HIGH' else '#f49a28'
    def xy(point_lat, point_lon):
        x = map_left + (point_lon - west) / (east - west) * map_width
        y = map_top + (mercator(north) - mercator(point_lat)) / (mercator(north) - mercator(south)) * map_height
        return int(x), int(y)
    if points:
        for ring_set in rings:
            for ring in ring_set:
                risk.polygon([(x - map_left, y - map_top) for x, y in (xy(point[1], point[0]) for point in ring)],
                             fill=colour + '66', outline=colour + 'ee', width=4)
    image.paste(overlay, (map_left, map_top), overlay)
    draw.rectangle((map_left, map_top, map_left + map_width, map_top + map_height), outline='white', width=2)
    marker_x, marker_y = xy(lat, lon)
    draw.ellipse((marker_x - 8, marker_y - 8, marker_x + 8, marker_y + 8), fill='#ed3d3d', outline='white', width=2)
    if item.get('raios', {}).get('coberto'):
        for strike_lat, strike_lon in lightning_points(bounds):
            strike_x, strike_y = xy(strike_lat, strike_lon)
            draw.ellipse((strike_x - 4, strike_y - 4, strike_x + 4, strike_y + 4), fill='#ffdf35', outline='#613f00', width=1)
    draw.rounded_rectangle((38, 310, 350, 365), radius=10, fill='#081522cc')
    layer = ('SEVERITY + OFFICIAL FLOOD AREA + LIGHTNING' if points and item.get('raios', {}).get('coberto') and severity is not None
             else 'SEVERITY + OFFICIAL FLOOD AREA' if points and severity is not None
             else 'SEVERITY NOWCASTING MAP' if severity is not None else 'LOCAL RISK MAP — SEVERITY UNAVAILABLE')
    draw.text((55, 325), layer, font=ImageFont.truetype(BOLD, 18), fill='white')
    # High-contrast, readable caption between map and presenter.
    draw.rounded_rectangle((30, 730, 690, 775), radius=10, fill='#081522')
    draw.text((48, 740), f"NOWCASTING: {item['headline'].upper()}", font=ImageFont.truetype(BOLD, 22), fill=colour)
    draw.rounded_rectangle((30, 785, 420, 1195), radius=20, fill='#142b3e')
    draw.text((50, 810), 'NOWCASTING SUMMARY', font=ImageFont.truetype(BOLD, 20), fill='#60e5cf')
    draw.text((50, 855), f"SEVERITY: {item['severity']}", font=ImageFont.truetype(BOLD, 23), fill=colour)
    headline_font = ImageFont.truetype(BOLD, 22)
    caption_font = ImageFont.truetype(FONT, 19)
    import textwrap
    y = 902
    for line in textwrap.wrap(item['headline'], width=26):
        draw.text((50, y), line.upper(), font=headline_font, fill='white'); y += 29
    y += 10
    for line in textwrap.wrap('Short-range risk signal for the city area.', width=30):
        draw.text((50, y), line, font=caption_font, fill='#dceaf4'); y += 25
    lightning = item.get('raios', {})
    lightning_text = (f"LIGHTNING NOWCAST: {lightning.get('raios_40km', 0)} strikes / 40 km / 30 min"
                      if lightning.get('coberto') else 'LIGHTNING NOWCAST: satellite coverage unavailable')
    for line in textwrap.wrap(lightning_text, width=31):
        draw.text((50, y + 12), line, font=ImageFont.truetype(FONT, 17), fill='#dceaf4'); y += 22
    draw.text((50, 1132), 'Severity layer: Lightning Agent', font=ImageFont.truetype(FONT, 15), fill='#bed3e4')
    draw.text((50, 1155), 'Subscribe for global weather updates.', font=ImageFont.truetype(FONT, 17), fill='#dceaf4')
    source_line = (f"Official source: {item['fonte']}" if item.get('oficial')
                   else 'Source: Open-Meteo • Not an official warning')
    draw.text((42, 1210), source_line, font=ImageFont.truetype(FONT, 18), fill='#bed3e4')
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
