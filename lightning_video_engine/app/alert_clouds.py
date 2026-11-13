"""Alert Shorts over real, moving GOES-19 infrared clouds, with the observed lightning on top.

Every key frame is an observed scan. The frames in between are computed from the motion between two
scans, so the video never shows clouds beyond the latest scan and never predicts their motion.
Any failure here raises, and the caller falls back to the static layout: an alert must not be lost
because the satellite archive had a bad minute.
"""
import json
import math
import re
import shutil
import subprocess
import textwrap
import urllib.request
import xml.etree.ElementTree as ElementTree
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parents[2]
BUCKET = 'https://noaa-goes19.s3.amazonaws.com'
PREFIX = 'ABI-L2-CMIPF/{:%Y/%j/%H}/OR_ABI-L2-CMIPF-M6C13'
SCANS = 7                 # one hour of ten-minute scans, the window /observado/mapa also covers
MAX_SCAN_AGE = 35         # minutes; an older picture would not describe the storm in the alert
MAX_SCAN_GAP = 25         # minutes; a longer hole would make the computed motion meaningless
W, H, FPS = 720, 1280, 25
STEPS = 20                # video frames from one scan to the next
HOLD = 40                 # video frames resting on the latest scan
SPAN_LAT = 7.0            # degrees shown top to bottom
CITY_Y = 500              # where the city sits on screen, clear of the panels
FONT = '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'
BOLD = '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'
AMBER, RED, TEXT, MUTED, PANEL = (255, 178, 56), (214, 48, 49), (244, 246, 248), (196, 205, 214), (9, 18, 29)
# Warm ground recedes, cloud goes grey to white, and cold tops step through the storm colours.
STOPS = [(35, '#050f1a'), (10, '#10263a'), (-10, '#3a5670'), (-25, '#8ca0b4'), (-38, '#dbe5ec'), (-44, '#7d5bb0'),
         (-52, '#a82c80'), (-62, '#ee5a3a'), (-70, '#fba43c'), (-78, '#fde68a'), (-90, '#ffffff')]
LABELS = {
    'pt': {'alert': 'ALERTA', 'flood': 'POTENCIAL DE ALAGAMENTO', 'lightning': 'Raios em 40 km', 'window': 'em 30 min',
           'nearest': 'Raio mais próximo', 'none': 'nenhum por perto', 'radar': 'Radar no centro', 'dry': 'sem chuva',
           'unread': 'indisponível', 'motion': 'Deslocamento', 'unknown': 'não determinado', 'protect': 'PROTEJA-SE',
           'scan': 'imagem de satélite', 'rain': 'chuva', 'now': 'O QUE OBSERVAMOS AGORA', 'source': 'Imagens observadas do GOES-19.',
           'legend': 'Pontos amarelos: raios. Cores fortes: topos frios.', 'official': 'Não é aviso oficial: siga a Defesa Civil.', 'ai': 'Apresentadora e voz geradas por IA.'},
    'es': {'alert': 'ALERTA', 'flood': 'POTENCIAL DE INUNDACIÓN', 'lightning': 'Rayos en 40 km', 'window': 'en 30 min',
           'nearest': 'Rayo más cercano', 'none': 'ninguno cerca', 'radar': 'Radar en el centro', 'dry': 'sin lluvia',
           'unread': 'no disponible', 'motion': 'Desplazamiento', 'unknown': 'no determinado', 'protect': 'PROTÉJASE',
           'scan': 'imagen de satélite', 'rain': 'lluvia', 'now': 'LO QUE OBSERVAMOS AHORA', 'source': 'Imágenes observadas del GOES-19.',
           'legend': 'Puntos amarillos: rayos. Colores fuertes: topes fríos.', 'official': 'No es un aviso oficial: siga a Defensa Civil.', 'ai': 'Presentadora y voz generadas por IA.'},
}
LABELS['en'] = {'alert': 'ALERT', 'flood': 'FLOOD POTENTIAL', 'official': 'OFFICIAL ALERT', 'lightning': 'Strikes within 40 km', 'window': 'in 30 min',
                'nearest': 'Nearest strike', 'none': 'none nearby', 'rain_now': 'Rain now', 'chance': 'Rain chance', 'chance_window': 'next 6 hours', 'dry': 'no rain',
                'unread': 'unavailable', 'protect': 'STAY SAFE', 'scan': 'satellite image', 'now': 'WHAT WE OBSERVE NOW', 'source': 'Observed GOES-19 images.',
                'legend': 'Yellow dots: lightning. Strong colours: cold tops.', 'not_official': 'Not an official warning: follow local services.',
                'ai': 'AI-generated presenter and voice.'}
EN_DIRECTIONS = {'norte': 'north', 'nordeste': 'northeast', 'leste': 'east', 'sudeste': 'southeast', 'sul': 'south', 'sudoeste': 'southwest', 'oeste': 'west', 'noroeste': 'northwest'}
MAX_VIEW = 65             # degrees of arc from below the satellite; farther away the disc is too oblique
RAIN_ES = {'fraca': 'débil', 'moderada': 'moderada', 'forte': 'fuerte', 'intensa': 'intensa', 'extrema': 'extrema'}


def font(path, size):
    return ImageFont.truetype(path, size)


def scan_start(key):
    found = re.search(r'_s(\d{4})(\d{3})(\d{2})(\d{2})', key)
    day = datetime(int(found[1]), 1, 1, tzinfo=timezone.utc) + timedelta(days=int(found[2]) - 1)
    return day + timedelta(hours=int(found[3]), minutes=int(found[4]))


def list_scans(now):
    keys = []
    for back in (2, 1, 0):
        prefix = PREFIX.format(now - timedelta(hours=back))
        with urllib.request.urlopen(f'{BUCKET}/?list-type=2&prefix={prefix}', timeout=30) as response:
            tree = ElementTree.fromstring(response.read())
        keys += [item.text for item in tree.iter() if item.tag.endswith('Key')]
    return sorted(keys, key=scan_start)


def choose_scans(keys, now):
    """The latest scans if they are recent and continuous; anything else raises."""
    chosen = keys[-SCANS:]
    if len(chosen) < SCANS:
        raise ValueError('imagens de satélite insuficientes')
    times = [scan_start(key) for key in chosen]
    if (now - times[-1]).total_seconds() / 60 > MAX_SCAN_AGE:
        raise ValueError('imagem de satélite antiga')
    if max((b - a).total_seconds() / 60 for a, b in zip(times, times[1:])) > MAX_SCAN_GAP:
        raise ValueError('falha na sequência de imagens de satélite')
    return chosen


def fetch(key, cache):
    """Each scan is downloaded once per pass, whichever cities need it."""
    cache.mkdir(parents=True, exist_ok=True)
    path = cache / Path(key).name
    if not path.exists():
        partial = path.with_suffix('.part')
        with urllib.request.urlopen(f'{BUCKET}/{key}', timeout=120) as response, open(partial, 'wb') as out:
            shutil.copyfileobj(response, out)
        partial.replace(path)
    return path


def prune(cache, keep):
    for path in cache.glob('*.nc'):
        if path.name not in keep:
            path.unlink(missing_ok=True)


def scan_angles(lat, lon, lon_origin=-75.2, height=42164160.0, semi_major=6378137.0, semi_minor=6356752.31414):
    """Latitude and longitude to the ABI fixed-grid angles (x, y), in radians (GOES-R PUG, vol. 3)."""
    lat, lon = np.radians(lat), np.radians(lon)
    eccentricity2 = 1 - semi_minor ** 2 / semi_major ** 2
    geocentric = np.arctan(semi_minor ** 2 / semi_major ** 2 * np.tan(lat))
    radius = semi_minor / np.sqrt(1 - eccentricity2 * np.cos(geocentric) ** 2)
    sx = height - radius * np.cos(geocentric) * np.cos(lon - math.radians(lon_origin))
    sy = -radius * np.cos(geocentric) * np.sin(lon - math.radians(lon_origin))
    sz = radius * np.sin(geocentric)
    return np.arcsin(-sy / np.sqrt(sx ** 2 + sy ** 2 + sz ** 2)), np.arctan(sz / sx)


def in_view(lat, lon, lon_origin=-75.2):
    """Whether GOES-19 sees this place well enough to show its clouds."""
    arc = math.cos(math.radians(lat)) * math.cos(math.radians(lon - lon_origin))
    return math.degrees(math.acos(max(-1, min(1, arc)))) <= MAX_VIEW


def view(lat):
    """Degrees per pixel keeping true shapes at this latitude."""
    per_y = SPAN_LAT / H
    return per_y / max(math.cos(math.radians(lat)), .2), per_y


def geo_grid(lat, lon):
    per_x, per_y = view(lat)
    lons = lon + (np.arange(W, dtype=np.float64) - W / 2) * per_x
    lats = lat - (np.arange(H, dtype=np.float64) - CITY_Y) * per_y
    return np.meshgrid(lons, lats)


def read_scan(path, grid):
    """One scan, resampled to the screen, in degrees Celsius."""
    import cv2
    import h5py
    with h5py.File(path, 'r') as file:
        projection = file['goes_imager_projection'].attrs
        first = lambda name: float(np.ravel(projection[name])[0])
        x, y = scan_angles(grid[1], grid[0], first('longitude_of_projection_origin'),
                           first('perspective_point_height') + first('semi_major_axis'),
                           first('semi_major_axis'), first('semi_minor_axis'))
        attr = lambda name, key: float(np.ravel(file[name].attrs[key])[0])
        ix = (x - attr('x', 'add_offset')) / attr('x', 'scale_factor')
        iy = (y - attr('y', 'add_offset')) / attr('y', 'scale_factor')
        data = file['CMI']
        if not (np.isfinite(ix).all() and np.isfinite(iy).all()):
            raise ValueError('área fora do disco do satélite')
        top, bottom = max(int(iy.min()) - 2, 0), min(int(iy.max()) + 3, data.shape[0])
        left, right = max(int(ix.min()) - 2, 0), min(int(ix.max()) + 3, data.shape[1])
        if bottom <= top or right <= left:
            raise ValueError('área fora do disco do satélite')
        raw = data[top:bottom, left:right]
        fill = np.ravel(data.attrs['_FillValue'])[0]
        kelvin = raw.astype(np.float32) * attr('CMI', 'scale_factor') + attr('CMI', 'add_offset')
        kelvin[raw == fill] = 300
    return cv2.remap(kelvin, (ix - left).astype(np.float32), (iy - top).astype(np.float32),
                     cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE) - 273.15


BASEMAP = ('https://gibs.earthdata.nasa.gov/wms/epsg4326/best/wms.cgi?SERVICE=WMS&VERSION=1.3.0&REQUEST=GetMap'
           '&LAYERS=BlueMarble_ShadedRelief_Bathymetry&STYLES=&CRS=EPSG:4326&BBOX={south:.4f},{west:.4f},{north:.4f},{east:.4f}'
           '&WIDTH={width}&HEIGHT={height}&FORMAT=image/jpeg')


def basemap(report, cache):
    """Land and sea in natural colour (NASA Blue Marble) under the clouds, or None when it cannot be read.

    The screen grid is plain latitude and longitude, so the map is asked for exactly that box and size.
    """
    import io
    lat, lon = report['lat'], report['lon']
    per_x, per_y = view(lat)
    box = dict(west=lon - W / 2 * per_x, east=lon + W / 2 * per_x, north=lat + CITY_Y * per_y,
               south=lat - (H - CITY_Y) * per_y, width=W, height=H)
    cache.mkdir(parents=True, exist_ok=True)
    path = cache / f"bluemarble_{lat:.3f}_{lon:.3f}.jpg"
    try:
        if not path.exists():
            with urllib.request.urlopen(BASEMAP.format(**box), timeout=60) as response:
                raw = response.read()
            Image.open(io.BytesIO(raw)).verify()
            path.write_bytes(raw)
        image = np.asarray(Image.open(path).convert('RGB').resize((W, H)), dtype=np.float32)
    except Exception as exc:
        print('Mapa de fundo indisponível; nuvens sobre fundo escuro:', exc, flush=True)
        return None
    if image.mean() < 8:          # an empty answer is black, not a map
        return None
    # A touch brighter and more saturated than the archive, so it still reads under the panels.
    grey = image.mean(axis=2, keepdims=True)
    return np.clip((grey + (image - grey) * 1.2) * 1.3 + 6, 0, 255)


def compose(field, base, colours):
    """Clouds over the map: clear sky shows the ground, cloud turns white, cold storm tops keep their colours."""
    cloud = np.clip((4 - field) / 34, 0, 1) ** .9 * .92
    shade = np.clip(150 + (10 - field) * 2.8, 150, 248)[..., None] * np.array([.97, .99, 1.0], np.float32)
    out = base * (1 - cloud[..., None]) + shade * cloud[..., None]
    storm = np.clip((-38 - field) / 10, 0, 1)[..., None]
    return np.clip(out * (1 - storm) + colours[to_index(field)] * storm, 0, 255).astype(np.uint8)


def palette():
    """256 colours for temperatures from +35 down to -95 degrees Celsius."""
    celsius = np.array([stop[0] for stop in STOPS], float)[::-1]
    colours = np.array([[int(stop[1][i:i + 2], 16) for i in (1, 3, 5)] for stop in STOPS], float)[::-1]
    scale = np.linspace(-95, 35, 256)
    return np.stack([np.interp(scale, celsius, colours[:, i]) for i in range(3)], axis=1).astype(np.uint8)


def to_index(field):
    return np.clip((field + 95) / 130 * 255, 0, 255).astype(np.uint8)


def computed_frames(a, b, steps):
    """The frames between two scans, moved along the motion measured between them."""
    import cv2
    pair = [cv2.resize(to_index(x), (W // 2, H // 2), interpolation=cv2.INTER_AREA) for x in (a, b)]
    flow = cv2.DISOpticalFlow_create(cv2.DISOPTICAL_FLOW_PRESET_MEDIUM)
    forward = cv2.resize(flow.calc(pair[0], pair[1], None), (W, H)) * 2
    backward = cv2.resize(flow.calc(pair[1], pair[0], None), (W, H)) * 2
    gx, gy = np.meshgrid(np.arange(W, dtype=np.float32), np.arange(H, dtype=np.float32))
    for step in range(steps):
        part = step / steps
        one = cv2.remap(a, gx - part * forward[..., 0], gy - part * forward[..., 1], cv2.INTER_LINEAR,
                        borderMode=cv2.BORDER_REPLICATE)
        two = cv2.remap(b, gx - (1 - part) * backward[..., 0], gy - (1 - part) * backward[..., 1], cv2.INTER_LINEAR,
                        borderMode=cv2.BORDER_REPLICATE)
        yield one * (1 - part) + two * part, part


def screen_xy(lat, lon, centre_lat, centre_lon):
    per_x, per_y = view(centre_lat)
    return (lon - centre_lon) / per_x + W / 2, (centre_lat - lat) / per_y + CITY_Y


def shadowed(draw, xy, value, size, fill=TEXT, bold=True, anchor='la'):
    face = font(BOLD if bold else FONT, size)
    draw.text((xy[0] + 1, xy[1] + 2), value, font=face, fill=(0, 0, 0, 200), anchor=anchor)
    draw.text(xy, value, font=face, fill=fill, anchor=anchor)


def map_layer(report, others):
    """State lines, nearby cities and the marked centre, drawn once for the whole video."""
    layer = Image.new('RGBA', (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    lat, lon = report['lat'], report['lon']
    for name, shade, width in (('estados-america-do-sul.json', 105, 1), ('paises-americas.json', 170, 2)):
        outlines = ROOT / 'templates' / name
        if outlines.exists():
            for ring in json.loads(outlines.read_text()):
                points = [screen_xy(y, x, lat, lon) for x, y in ring]
                if any(-40 <= px <= W + 40 and -40 <= py <= H + 40 for px, py in points):
                    draw.line(points, fill=(232, 238, 244, shade), width=width)
    # An official warning shows its real area, not only the city.
    geometry = report.get('geometria_alerta') or {}
    polygons = geometry.get('coordinates') or []
    for polygon in ([polygons] if geometry.get('type') == 'Polygon' else polygons):
        for ring in polygon:
            draw.polygon([screen_xy(y, x, lat, lon) for x, y in ring], fill=(233, 72, 74, 70), outline=(255, 110, 110, 255), width=3)
    per_x, per_y = view(lat)
    taken = [(W / 2, CITY_Y)]
    for name, other_lat, other_lon in others:
        x, y = screen_xy(other_lat, other_lon, lat, lon)
        if not (40 < x < W - 170 and 285 < y < 700) or any(abs(x - a) < 150 and abs(y - b) < 40 for a, b in taken):
            continue
        taken.append((x, y))
        draw.ellipse((x - 3, y - 3, x + 3, y + 3), fill=(244, 246, 248, 230))
        shadowed(draw, (x + 8, y - 11), name, 18, (244, 246, 248, 235), bold=False)
    radius = 40 / 111.2 / per_y
    x, y = W / 2, CITY_Y
    for i in range(0, 60, 2):
        start, end = i / 60 * 2 * math.pi, (i + 1) / 60 * 2 * math.pi
        draw.line([(x + radius * math.cos(start), y + radius * math.sin(start)),
                   (x + radius * math.cos(end), y + radius * math.sin(end))], fill=(255, 255, 255, 235), width=2)
    star = [(x + (14 if i % 2 == 0 else 6) * math.sin(i * math.pi / 5), y - (14 if i % 2 == 0 else 6) * math.cos(i * math.pi / 5))
            for i in range(10)]
    draw.polygon(star, fill=(31, 111, 235, 255), outline=(255, 255, 255, 255))
    # A long name goes under the circle, shrunk if needed, so that it is never cut by the screen edge.
    name, size = report['nome'].split(',')[0], 26
    while font(BOLD, size).getlength(name) > W - 40 and size > 14:
        size -= 1
    if x + radius + 10 + font(BOLD, size).getlength(name) <= W - 12:
        shadowed(draw, (x + radius + 10, y - 16), name, size)
    else:
        shadowed(draw, (x, y + radius + 8), name, size, anchor='ma')
    return np.asarray(layer, dtype=np.float32) / 255


def lightning_cells(flashes, report):
    """(minutes before the end of the map, x, y, count) of the observed cells on screen."""
    step = flashes.get('idade_passo_min', 10)
    cells = []
    for lat, lon, count, _, age in flashes.get('pontos', []):
        x, y = screen_xy(lat, lon, report['lat'], report['lon'])
        if 0 <= x < W and 0 <= y < H:
            cells.append(((age + .5) * step, x, y, count))
    return np.array(cells, dtype=np.float32).reshape(-1, 4)


def add_lightning(frame, cells, minutes_before):
    """Cells of the ten minutes up to this moment, the newest brightest."""
    import cv2
    if not len(cells):
        return frame
    age = cells[:, 0] - minutes_before
    shown = cells[(age >= 0) & (age <= 10)]
    if not len(shown):
        return frame
    age = shown[:, 0] - minutes_before
    core, edge = np.zeros((H, W), np.uint8), np.zeros((H, W), np.uint8)
    for x, y, count, old in zip(shown[:, 1], shown[:, 2], shown[:, 3], age):
        size = 3 if count >= 3 else 2
        cv2.circle(edge, (int(x), int(y)), size + 2, 255, -1, cv2.LINE_AA)
        cv2.circle(core, (int(x), int(y)), size, int(255 * (1 - .45 * old / 10)), -1, cv2.LINE_AA)
    # A dark rim keeps the yellow readable over the orange of the coldest tops.
    out = frame.astype(np.float32) * (1 - edge[..., None].astype(np.float32) / 255 * .85)
    mix = core[..., None].astype(np.float32) / 255
    return np.clip(out * (1 - mix) + mix * np.array([255, 240, 60], np.float32), 0, 255).astype(np.uint8)


def write_loop(path, fields, times, cells, end, layer, clock, label, base=None):
    """A loop of one hour of clouds, rendered once and repeated for the whole narration."""
    colours = palette()
    encoder = subprocess.Popen(['ffmpeg', '-y', '-v', 'error', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-s', f'{W}x{H}',
                                '-r', str(FPS), '-i', '-', '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '20',
                                '-threads', '2', '-pix_fmt', 'yuv420p', str(path)], stdin=subprocess.PIPE)
    alpha, rgb = layer[..., 3:4], layer[..., :3] * 255

    def emit(field, moment, minutes_before):
        frame = colours[to_index(field)] if base is None else compose(field, base, colours)
        frame = add_lightning(frame, cells, minutes_before)
        frame = (frame * (1 - alpha) + rgb * alpha).astype(np.uint8)
        stamp = Image.new('RGB', (190, 66), (0, 0, 0))
        mask = Image.new('L', (190, 66), 0)
        draw = ImageDraw.Draw(mask)
        draw.text((188, 0), clock(moment), font=font(BOLD, 38), fill=255, anchor='ra')
        draw.text((188, 44), label, font=font(FONT, 15), fill=225, anchor='ra')
        tint = Image.fromarray(frame[210:276, 500:690])
        soft = mask.filter(ImageFilter.GaussianBlur(3)).point(lambda v: int(v * .8))
        tint.paste(stamp, (0, 0), soft)
        tint.paste(Image.new('RGB', (190, 66), TEXT), (0, 0), mask)
        frame[210:276, 500:690] = np.asarray(tint)
        encoder.stdin.write(frame.tobytes())

    try:
        for index in range(len(fields) - 1):
            span = (times[index + 1] - times[index]).total_seconds() / 60
            for field, part in computed_frames(fields[index], fields[index + 1], STEPS):
                moment = times[index] + timedelta(minutes=span * part)
                emit(field, moment, (end - moment).total_seconds() / 60)
        for _ in range(HOLD):
            emit(fields[-1], times[-1], 0)
    finally:
        encoder.stdin.close()
        encoder.wait(timeout=120)
    if encoder.returncode:
        raise RuntimeError('falha ao codificar as nuvens')


def global_cards(report, labels):
    lightning = report.get('raios') or {}
    near = lightning.get('mais_proximo')
    covered = lightning.get('coberto')
    count = lightning.get('raios_40km')
    rain = report.get('chuva_atual_mm')
    return [(labels['lightning'], f'{count}' if covered and isinstance(count, int) else labels['unread'], labels['window'] if covered else ''),
            (labels['nearest'], f"{near['km']:.0f} km" if covered and near else labels['none'] if covered else labels['unread'],
             EN_DIRECTIONS.get(near.get('direcao'), '') if covered and near else ''),
            (labels['rain_now'], f'{rain:.1f} mm' if rain else labels['dry'], ''),
            (labels['chance'], f"{report.get('probabilidade_6h', 0)}%", labels['chance_window'])]


def panel(report, labels, scene, time):
    """Everything over the clouds for one scene; only the clouds and the clock move."""
    array = np.zeros((H, W, 4), np.uint8)
    array[..., :3] = PANEL
    array[:285, :, 3] = np.linspace(242, 0, 285)[:, None].astype(np.uint8)
    array[640:760, :, 3] = np.linspace(0, 240, 120)[:, None].astype(np.uint8)
    array[760:, :, 3] = 240
    image = Image.fromarray(array)
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, W, 6), fill=AMBER + (255,))
    shadowed(draw, (32, 26), report.get('marca', 'TROVOX TEMPO'), 25, AMBER)
    flood = report.get('secao') == 'alagamentos-sp'
    chip = labels['flood'] if flood else labels['official'] if report.get('oficial') else labels['alert']
    face = font(BOLD, 21)
    width = int(face.getlength(chip)) + 28
    draw.rounded_rectangle((32, 70, 32 + width, 106), 8, fill=RED + (255,))
    draw.text((46, 76), chip, font=face, fill=(255, 255, 255, 255))
    name = f"{report['nome']}, {report['uf']}"
    size = 50
    while font(BOLD, size).getlength(name) > 650 and size > 28:
        size -= 2
    shadowed(draw, (32, 118), name, size)
    shadowed(draw, (32, 182), time.strftime('%b %d, %Y • %H:%M' if labels.get('rain_now') else '%d/%m/%Y • %H:%M'), 25, MUTED, bold=False)
    if scene == 'facts':
        shadowed(draw, (32, 712), labels['now'], 22, AMBER)
        near = (report.get('raios') or {}).get('mais_proximo')
        rain = (report.get('chuva') or {})
        rain_name = rain.get('nome')
        if report.get('idioma', '').startswith('es'):
            rain_name = RAIN_ES.get(rain_name, rain_name)
        motion = (report.get('nowcasting') or {}).get('deslocamento')
        count = (report.get('raios') or {}).get('raios_40km')
        cards = [] if labels.get('rain_now') else [
            (labels['lightning'].replace('40', str(report.get('raio_km') or 40)), f'{count}' if isinstance(count, int) else labels['unread'], labels['window']),
            (labels['nearest'], ('< 1 km' if near['km'] < 1 else f"{near['km']:.0f} km") if near else labels['none'], near.get('direcao', '') if near else ''),
            (labels['radar'], f"{labels['rain']} {rain_name}" if rain_name else (labels['dry'] if rain.get('coberto') else labels['unread']), ''),
            (labels['motion'], f"{motion['velocidade_kmh']} km/h" if motion else labels['unknown'], motion['para'] if motion else '')]
        if labels.get('rain_now'):
            cards = global_cards(report, labels)
        for index, (title, value, detail) in enumerate(cards):
            x, y = 30 + (index % 2) * 335, 748 + (index // 2) * 112
            draw.rounded_rectangle((x, y, x + 325, y + 102), 14, fill=(26, 40, 56, 255))
            draw.text((x + 18, y + 12), title, font=font(FONT, 19), fill=MUTED)
            big = 34 if len(value) <= 15 else 25
            draw.text((x + 18, y + 38), value, font=font(BOLD, big), fill=(255, 255, 255, 255))
            if detail:
                draw.text((x + 18, y + 77), detail, font=font(FONT, 17), fill=MUTED)
    else:
        shadowed(draw, (32, 712), labels['protect'], 26, AMBER)
        y = 752
        for item in report['recomendacoes']:
            draw.ellipse((36, y + 9, 47, y + 20), fill=AMBER + (255,))
            for line in textwrap.wrap(item, 48):
                draw.text((60, y), line, font=font(FONT, 24), fill=TEXT)
                y += 31
            y += 9
    reason = report.get('motivo_tela') or (report.get('motivos') or [''])[0]
    if reason:
        y = 985
        for line in textwrap.wrap(reason[0].upper() + reason[1:], 34)[:4]:
            draw.text((240, y), line, font=font(BOLD, 22), fill=TEXT)
            y += 28
    notice = f"Official source: {report.get('fonte')}" if report.get('oficial') and labels.get('not_official') else labels.get('not_official') or labels['official']
    for index, line in enumerate((labels['source'], labels['legend'], notice)):
        draw.text((240, 1106 + index * 23), line, font=font(FONT, 17), fill=MUTED)
    return image


HOOK_SECONDS = 2.5


def hook_layer(report):
    """The big number shown over the satellite in the first seconds, or None when there is no reliable count."""
    from .city_shorts import lightning_hook
    language = report.get('idioma', 'pt')
    if report.get('marca') == 'TROVOX GLOBAL' or language.startswith('en') or report.get('secao') == 'alagamentos-sp':
        return None
    count = lightning_hook(report.get('raios'))
    if not count:
        return None
    spanish = language.startswith('es')
    big = f"⚡ {count} {'RAYOS' if spanish else 'RAIOS'}"
    line = f"{'en 30 min cerca de' if spanish else 'em 30 min perto de'} {report['nome']}"
    image = Image.new('RGBA', (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((24, 300, W - 24, 560), 26, fill=(8, 14, 22, 215), outline=RED + (255,), width=5)
    size = 96
    while font(BOLD, size).getlength(big) > W - 100 and size > 48:
        size -= 4
    shadowed(draw, (W // 2, 400), big, size, AMBER, anchor='mm')
    size = 36
    while font(BOLD, size).getlength(line) > W - 100 and size > 22:
        size -= 2
    shadowed(draw, (W // 2, 500), line, size, anchor='mm')
    return image


def nearby(report):
    if report.get('marca') == 'TROVOX GLOBAL':
        from .world_alerts import CITIES as WORLD
        return [(city[0].split(',')[0], city[2], city[3]) for key, city in WORLD.items() if key != report['cidade']]
    from .city_shorts import CITIES
    return [(city[0], city[2], city[3]) for key, city in CITIES.items()
            if key != report['cidade'] and not key.startswith('sp-')]


def render_clouds(directory, report, resources):
    """Compose short.mp4. Raises when the observed data cannot support the video."""
    from .shorts_locales import city_timezone
    from .shorts_presenter import synchronize
    if not in_view(report['lat'], report['lon']):
        raise ValueError('local fora do alcance do GOES-19')
    duration = float(subprocess.check_output(['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0',
                                              str(directory / 'voz.mp3')]))
    if duration > 60:
        raise ValueError('narração excedeu 60 segundos; vídeo não publicado')
    now = datetime.now(timezone.utc)
    keys = choose_scans(list_scans(now), now)
    cache = directory.parent / 'goes-cache'
    paths = [fetch(key, cache) for key in keys]
    prune(cache, {path.name for path in paths})
    grid = geo_grid(report['lat'], report['lon'])
    fields = [read_scan(path, grid) for path in paths]
    times = [scan_start(key) for key in keys]
    flashes = resources.json('/observado/mapa')
    end = datetime.fromisoformat(flashes['fim'].replace('Z', '+00:00'))
    cells = lightning_cells(flashes, report)
    zone = ZoneInfo(report.get('timezone') or city_timezone(report['cidade'], report['uf']))
    language = report.get('idioma', '')
    labels = LABELS['es' if language.startswith('es') else 'en' if language.startswith('en') else 'pt']
    write_loop(directory / 'nuvens.mp4', fields, times, cells, end, map_layer(report, nearby(report)),
               lambda moment: moment.astimezone(zone).strftime('%H:%M'), labels['scan'],
               base=basemap(report, directory.parent / 'basemap-cache'))
    checked = datetime.fromisoformat(report['verificado_em'].replace('Z', '+00:00')).astimezone(zone)
    panel(report, labels, 'facts', checked).save(directory / 'painel-1.png')
    panel(report, labels, 'protect', checked).save(directory / 'painel-2.png')
    hook = hook_layer(report)
    (hook or Image.new('RGBA', (W, H), (0, 0, 0, 0))).save(directory / 'gancho.png')
    print('Sincronizando apresentadora para o Short...', flush=True)
    presenter = synchronize(directory)
    change = duration * .62
    music = ROOT / 'templates/fundo-musical.wav'
    inputs = ['-stream_loop', '-1', '-i', str(directory / 'nuvens.mp4'), '-loop', '1', '-i', str(directory / 'painel-1.png'),
              '-loop', '1', '-i', str(directory / 'painel-2.png'), '-i', str(presenter), '-i', str(directory / 'voz.mp3'),
              '-loop', '1', '-i', str(directory / 'gancho.png')]
    if music.exists():
        inputs += ['-stream_loop', '-1', '-i', str(music)]
    video = (f"[0:v]fps={FPS},setpts=PTS-STARTPTS[bg];"
             f"[bg][1:v]overlay=0:0:enable='lt(t,{change:.2f})':shortest=0[a];"
             f"[a][2:v]overlay=0:0:enable='gte(t,{change:.2f})':shortest=0[b];"
             "[3:v]crop=trunc(iw*0.70/2)*2:trunc(ih*0.62/2)*2:(iw-ow)/2:ih*0.06,"
             "scale=190:230:force_original_aspect_ratio=increase,crop=190:230,setsar=1,"
             f"pad=198:238:4:4:color=0xFFB238,fps={FPS},setpts=PTS-STARTPTS[p];"
             "[b][p]overlay=30:980[c];"
             f"[c][5:v]overlay=0:0:enable='lt(t,{HOOK_SECONDS})':shortest=0[v]")
    audio = ('[4:a]volume=1[n];[6:a]volume=0.08[m];[n][m]amix=inputs=2:duration=first:normalize=0,alimiter=limit=0.95[s]'
             if music.exists() else '[4:a]anull[s]')
    subprocess.run(['ffmpeg', '-y', '-v', 'error', *inputs, '-filter_complex', f'{video};{audio}', '-map', '[v]', '-map', '[s]',
                    '-t', f'{duration:.3f}', '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '21', '-threads', '2',
                    '-pix_fmt', 'yuv420p', '-r', str(FPS), '-c:a', 'aac', '-movflags', '+faststart',
                    str(directory / 'short.mp4')], check=True, timeout=240)
    return directory / 'short.mp4'
