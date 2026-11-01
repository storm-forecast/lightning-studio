"""Task: is it raining at a point, by radar, for the agent to say so in an answer.

The map already answers this in the browser, straight from the provider's tiles. The agent runs on the
server and cannot see that, so it reads a tile of its own: one 256x256 PNG for the point, which is tens of
kilobytes and is cached until the provider publishes the next frame.

The classes come from the order of the provider's own palette, read off their tiles, because they stopped
publishing the scheme that carried dBZ in January. So these are intensities and not millimetres, and the
text says so. Where no radar looks the answer is "not measured here", never "it is not raining": the two
are indistinguishable in a radar picture and only one of them is true.
"""

import io
import time
import urllib.request
from typing import Optional

import numpy as np
from PIL import Image

import functools
import logging
import threading
logger = logging.getLogger(__name__)
_radar_lock = threading.RLock()
def heavy(fn):
    @functools.wraps(fn)
    def wrapped(*args, **kwargs):
        with _radar_lock:
            return fn(*args, **kwargs)
    return wrapped

INDEX_URL = "https://api.rainviewer.com/public/weather-maps.json"
INDEX_TTL = 300        # seconds; their frames are ten minutes apart
ZOOM = 7               # match Trovox's maximum native radar zoom
TILE_SIZE = 512        # match the displayed tile, including its rendered palette
MAX_FRAME_AGE = 30 * 60  # a stalled feed cannot describe current conditions on the road
NEARBY = 512           # retain the previous coverage-search distance on the finer grid; used only
# to tell "no rain" from "no radar": a
# transparent pixel means both, and they cannot be told apart at one point. If the radar is
# painting anything within a few hundred kilometres, there is a radar looking at this region.
TOL = 15               # per channel, to call a pixel a palette colour at all
CLASSES = ["fraca", "moderada", "forte", "intensa", "extrema"]

# The palette, with the class of each colour. The magenta ramp is the top of the scale, not sleet: its
# pixels sit at a median latitude of 33.6 degrees while the snow ramp sits at 60.5.
_PALETTE = (
    [(h, 0) for h in ("88ddee", "6cd1eb", "51c5e8", "36bae5", "1baee2", "00a3e0", "009ad5", "0091ca",
                      "0088bf", "007fb4", "0077aa", "0070a3", "00699c")]
    + [(h, 1) for h in ("006295", "005b8e", "005588", "005180", "004e78", "004a70", "004768")]
    + [(h, 2) for h in ("ffe000", "ffd200", "ffc500", "ffb700")]
    + [(h, 3) for h in ("ffaa00", "ff9f00", "ff9500", "ff8b00", "ff8100", "ff4400", "f23600", "e62800",
                        "d91b00", "cd0d00", "c10000")]
    + [(h, 4) for h in ("ffaaff", "ff9fff", "ff95ff", "ff8bff", "ff81ff", "ff77ff", "ff6cff", "ff62ff",
                        "ff58ff", "ff4eff")]
    + [(h, -1) for h in ("bfffff", "a5e5ff", "92d2ff", "78b8ff", "72b2ff", "6babff", "5b9bff")]
)
_COLORS = np.array([[int(h[i:i + 2], 16) for i in (0, 2, 4)] for h, _ in _PALETTE], np.int16)
_CLASS_OF = np.array([c for _, c in _PALETTE], np.int8)

_index: tuple = (0.0, None)   # (fetched at, payload)
_tiles: dict = {}             # (path, x, y) -> ndarray, cleared when the frame changes


def _get_index() -> Optional[dict]:
    global _index
    if time.time() - _index[0] < INDEX_TTL and _index[1] is not None:
        return _index[1]
    try:
        with urllib.request.urlopen(INDEX_URL, timeout=10) as r:
            data = __import__("json").load(r)
    except Exception as e:
        logger.warning("radar index unavailable: %s", e)
        return _index[1]
    if _index[1] and data.get("radar", {}).get("past", [{}])[-1].get("path") != \
            _index[1].get("radar", {}).get("past", [{}])[-1].get("path"):
        _tiles.clear()
    _index = (time.time(), data)
    return data


def _tile(host: str, path: str, x: int, y: int) -> Optional[np.ndarray]:
    key = (path, x, y)
    if key not in _tiles:
        url = f"{host}{path}/{TILE_SIZE}/{ZOOM}/{x}/{y}/2/1_1.png"
        try:
            with urllib.request.urlopen(url, timeout=15) as r:
                raw = r.read()
        except Exception as e:
            logger.warning("radar tile %s failed: %s", url, e)
            return None
        if len(_tiles) >= 16:  # ~16 MiB of RGBA tiles, as with the former 64 x 256px cache
            _tiles.clear()
        _tiles[key] = np.asarray(Image.open(io.BytesIO(raw)).convert("RGBA"))
    return _tiles[key]


def _pixel_raw(lat: float, lon: float) -> tuple:
    import math

    n = TILE_SIZE * 2 ** ZOOM
    xp = (lon + 180.0) / 360.0 * n
    s = math.sin(math.radians(max(-85.0, min(85.0, lat))))
    yp = (0.5 - math.log((1 + s) / (1 - s)) / (4 * math.pi)) * n
    return int(xp // TILE_SIZE), int(yp // TILE_SIZE), int(xp) % TILE_SIZE, int(yp) % TILE_SIZE


@heavy
def _pixel(lat: float, lon: float) -> tuple:
    return _pixel_raw(lat, lon)


def _classe(data: np.ndarray, px: int, py: int) -> tuple:
    """(class, snow) at the requested pixel, not the strongest echo kilometres away.

    At zoom 4, a 5x5 maximum painted nearby storms onto dry road up to two pixels away.
    Keep the coverage search separate: nearby echoes establish coverage, never local intensity.
    """
    sub = data[py:py + 1, px:px + 1].reshape(-1, 4)
    visiveis = sub[sub[:, 3] > 0]
    if not len(visiveis):
        return None, False
    d = np.abs(visiveis[:, None, :3].astype(np.int16) - _COLORS[None, :, :]).max(axis=2)
    perto = d.min(axis=1)
    onde = _CLASS_OF[d.argmin(axis=1)][perto <= TOL]
    if not len(onde):
        return None, False
    chuva = onde[onde >= 0]
    return (int(chuva.max()) if len(chuva) else None), bool((onde < 0).any())


def _fresh_past(index: Optional[dict]) -> list:
    past = (index or {}).get("radar", {}).get("past") or []
    stamp = past[-1].get("time") if past else None
    if stamp is None or not -300 <= time.time() - stamp <= MAX_FRAME_AGE:
        return []
    return past


def radar_frame() -> Optional[dict]:
    """The same current frame used to classify road points, for the map to display."""
    index = _get_index()
    past = _fresh_past(index)
    if not past:
        return None
    return {"host": index["host"], "radar": {"past": [past[-1]]}}


def rain_at(lat: float, lon: float) -> Optional[dict]:
    """Rain at the point's radar pixel, or None when no recent frame could be read.
    `coberto` False means no radar looks there, which is not the same as no rain."""
    index = _get_index()
    past = _fresh_past(index)
    if not past:
        return None
    frame = past[-1]
    tx, ty, px, py = _pixel(lat, lon)
    data = _tile(index["host"], frame["path"], tx, ty)
    if data is None:
        return None
    melhor, neve = _classe(data, px, py)
    volta = data[max(py - NEARBY, 0):py + NEARBY + 1, max(px - NEARBY, 0):px + NEARBY + 1]
    return {"coberto": bool((volta[..., 3] > 0).any()),
            "classe": melhor, "nome": CLASSES[melhor] if melhor is not None else None,
            "neve": neve, "hora": frame["time"]}


@heavy
def rain_at_many(points) -> list:
    """One current radar reading per point, loading each needed tile only once.

    A detailed route can cross thousands of radar pixels. Calling :func:`rain_at` for every
    pixel repeated coordinate conversion and coverage scans, turning a route refresh into seconds
    of CPU after the tiles were already in memory.
    """
    points = list(points)
    index = _get_index()
    past = _fresh_past(index)
    if not past:
        return [None] * len(points)
    frame = past[-1]
    pixels = [_pixel_raw(float(lat), float(lon)) for lat, lon in points]
    needed = {(x, y) for x, y, _, _ in pixels}
    tiles = {(x, y): _tile(index["host"], frame["path"], x, y) for x, y in needed}
    covered = {key: bool(data is not None and (data[..., 3] > 0).any()) for key, data in tiles.items()}
    result = []
    for x, y, px, py in pixels:
        data = tiles[x, y]
        if data is None:
            result.append(None)
            continue
        classe, neve = _classe(data, px, py)
        result.append({"coberto": covered[x, y], "classe": classe,
                       "nome": CLASSES[classe] if classe is not None else None,
                       "neve": neve, "hora": frame["time"]})
    return result


# How long the rain has held at a point: the difference between heavy rain and a flood question, and the
# one input floodStep has that nothing else here asks for. Frames are ten minutes apart, so this reads a
# handful of them backwards from now; the tiles are the same ones rain_at already fetched and cached, so
# the ones it needs are usually there already.
PERSIST_FRAMES = 5      # ~50 minutes back, well past FLOOD_RUN_MINUTES
PERSIST_CLASS = 2       # the radar's yellow: below it there is no flood question to ask


def rain_minutes_at(lat: float, lon: float) -> Optional[float]:
    """Minutes the rain has been at PERSIST_CLASS or above without a break, or None if unreadable.

    Zero is a real answer -- it is raining hard now and was not ten minutes ago -- and is what tells a
    passing squall from the rain that fills a street. None means the frames could not be read, which is
    not the same thing and must not be counted as a break.
    """
    index = _get_index()
    past = _fresh_past(index)
    if not past:
        return None
    tx, ty, px, py = _pixel(lat, lon)
    quadros = past[-PERSIST_FRAMES:]
    agora = quadros[-1].get("time")
    if agora is None:
        return None
    desde, leu = None, False
    for frame in reversed(quadros):
        data = _tile(index["host"], frame["path"], tx, ty)
        if data is None:
            break
        leu = True
        classe, _ = _classe(data, px, py)
        if classe is None or classe < PERSIST_CLASS:
            break
        desde = frame.get("time")
    if not leu:
        return None          # nothing was read; a zero here would be read as "it is not raining"
    if desde is None:
        return 0.0           # read, and the newest frame is below the threshold: no spell to measure
    return max(0.0, (agora - desde) / 60.0)


def format_rain(r: Optional[dict]) -> str:
    """One line for the agent's context. Silence where there is no radar would read as "no rain"."""
    from datetime import datetime, timezone

    if r is None:
        return "- Chuva (radar): não foi possível consultar o radar agora."
    quando = datetime.fromtimestamp(r["hora"], timezone.utc).strftime("%H:%M UTC")
    if r["classe"] is None and not r["coberto"]:
        return ("- Chuva (radar): nenhum radar parece cobrir esta região (não há eco algum em centenas de "
                "km). Diga que não dá para saber se chove aqui por radar; NÃO diga que não está chovendo.")
    if r["classe"] is None:
        return (f"- Chuva (radar, {quando}): há radar na região e ele não mostra chuva neste ponto"
                + (" (há neve por perto)." if r["neve"] else "."))
    return (f"- Chuva (radar, {quando}): está chovendo, intensidade {r['nome'].upper()} na escala do radar"
            + (", e o topo da escala costuma acompanhar granizo" if r["classe"] >= 4 else "")
            + ". É intensidade, não milímetros.")


@heavy
def approaching_heavy_rain(lat, lon):
    """Conservative regional trend from three fresh radar frames; no motion from a single frame."""
    import math
    index = _get_index()
    frames = _fresh_past(index)
    if not frames or len(frames) < 3:
        return None
    frames = frames[-3:]
    if not 600 <= frames[-1]['time'] - frames[0]['time'] <= 1800:
        return None
    points = []
    for dy in range(-60, 61, 10):
        for dx in range(-60, 61, 10):
            distance = math.hypot(dx, dy)
            if distance <= 60:
                y, x = lat + dy/111.2, lon + dx/(111.2*math.cos(math.radians(lat)))
                points.append((distance, _pixel(y, x)))
    nearest = []
    for frame in frames:
        distances = []
        for distance, (tx,ty,px,py) in points:
            data = _tile(index['host'], frame['path'], tx, ty)
            if data is None:
                return None
            rank, _ = _classe(data, px, py)
            if rank is not None and rank >= 2:
                distances.append(distance)
        if not distances:
            return None
        nearest.append(min(distances))
    # Require a consistent reduction, still outside the central 10 km.
    if not nearest[0] > nearest[1] > nearest[2] >= 10:
        return None
    speed = (nearest[0]-nearest[-1]) / ((frames[-1]['time']-frames[0]['time'])/3600)
    if not 10 <= speed <= 80:
        return None
    return {'distancia_km': round(nearest[-1],1), 'hora': frames[-1]['time'],
            'quadros': [f['time'] for f in frames], 'metodo': 'tendência regional de ecos fortes; não rastreia uma célula individual'}
