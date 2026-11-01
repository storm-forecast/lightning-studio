"""City-only nowcasting monitor. SQLite dispatch history survives process restarts."""
import asyncio
import json
import os
import sqlite3
import subprocess
import threading
import uuid
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from .shorts_locales import SPANISH_CITIES, city_timezone
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

def utc_now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def rain_at(*args):
    from .shorts_rain import rain_at as operation
    return operation(*args)


def rain_approach(lat, lon):
    from .shorts_rain import approaching_heavy_rain
    return approaching_heavy_rain(lat, lon)


def rain_duration(lat, lon):
    from .shorts_rain import rain_minutes_at
    return rain_minutes_at(lat, lon)


class AgentSource:
    def __init__(self, api):
        self.api = api.rstrip('/')

    def read(self, path, **query):
        from urllib.parse import urlencode
        from urllib.request import urlopen
        url = self.api + path + ('?' + urlencode(query) if query else '')
        with urlopen(url, timeout=60) as response:
            return response.read()

    def json(self, path, **query):
        return json.loads(self.read(path, **query))


CITIES = {
    'rio-de-janeiro': ('Rio de Janeiro', 'RJ', -22.907, -43.173),
    'salvador': ('Salvador', 'BA', -12.977, -38.501),
    'florianopolis': ('Florianópolis', 'SC', -27.595, -48.548),
    'maceio': ('Maceió', 'AL', -9.666, -35.735),
    'gramado': ('Gramado', 'RS', -29.374, -50.876),
    'sao-paulo': ('São Paulo', 'SP', -23.551, -46.633),
    'curitiba': ('Curitiba', 'PR', -25.429, -49.267),
    'porto-alegre': ('Porto Alegre', 'RS', -30.034, -51.230),
    'santa-maria': ('Santa Maria', 'RS', -29.6858, -53.8072),
    'brasilia': ('Brasília', 'DF', -15.7939, -47.8828),
    'belo-horizonte': ('Belo Horizonte', 'MG', -19.9167, -43.9345),
    'campo-grande': ('Campo Grande', 'MS', -20.4697, -54.6201),
    'manaus': ('Manaus', 'AM', -3.1190, -60.0217),
    'cordoba': ('Córdoba', 'Argentina', -31.4065, -64.1885),
    'buenos-aires': ('Buenos Aires', 'Argentina', -34.6037, -58.3816),
    'santa-cruz-de-la-sierra': ('Santa Cruz de la Sierra', 'Bolivia', -17.7833, -63.1821),
    'santiago': ('Santiago', 'Chile', -33.4489, -70.6693),
    'bogota': ('Bogotá', 'Colombia', 4.7110, -74.0721),
    'guayaquil': ('Guayaquil', 'Ecuador', -2.1709, -79.9224),
    'asuncion': ('Asunción', 'Paraguay', -25.2637, -57.5759),
    'lima': ('Lima', 'Perú', -12.0464, -77.0428),
    'montevideo': ('Montevideo', 'Uruguay', -34.9011, -56.1645),
    'caracas': ('Caracas', 'Venezuela', 10.4806, -66.9036),
}


def fresh(value, now):
    if not value:
        return False
    t = datetime.fromisoformat(value.replace('Z', '+00:00')).replace(tzinfo=None)
    return 0 <= (now - t).total_seconds() <= 900


def evaluate(key, resources):
    name, state, lat, lon = CITIES[key]
    now = utc_now()
    lightning = resources.json('/alertas/situacao', lat=lat, lon=lon)
    point = resources.json('/observado/ponto', lat=lat, lon=lon, raio_km=40).get('agora')
    valid = point and any(fresh(point.get(k), now) for k in ('raios_ate', 'nuvens_de', 'cod_de', 'meteo_de'))
    radar = rain_at(lat, lon)
    reasons = []
    radar_fresh = bool(radar and radar.get('coberto') and not radar.get('neve') and
                       radar.get('classe') is not None and radar.get('hora') is not None and
                       0 <= (now - datetime.fromtimestamp(radar['hora'], timezone.utc)
                             .replace(tzinfo=None)).total_seconds() <= 900)
    lightning_fresh = not lightning['dados_atrasados'] and lightning['coberto']
    near = lightning.get('mais_proximo')
    recent_lightning = bool(lightning_fresh and near and near.get('km', float('inf')) <= 40 and
                            0 <= near.get('minutos_atras', float('inf')) <= 15)
    strong_rain_minutes = rain_duration(lat, lon) if radar_fresh and radar['classe'] >= 2 else None
    persistent_yellow = bool(strong_rain_minutes is not None and strong_rain_minutes >= 10)
    if radar_fresh and recent_lightning:
        reasons.append('chuva detectada no radar e raios recentes na região')
    if radar_fresh and persistent_yellow:
        reasons.append('chuva forte persistente na escala do radar na área monitorada')
    incoming_rain = rain_approach(lat, lon) if reasons else None
    advice = ['Procure abrigo em uma edificação ou veículo fechado.',
              'Evite áreas abertas, árvores isoladas e atividades na água.',
              'Não atravesse ruas alagadas. Acompanhe os avisos da Defesa Civil.']
    motion = point.get('deslocamento') if valid else None
    text = f"Atenção, {name}, {state}. Monitoramento da área até 40 quilômetros do centro. "
    text += '; '.join(reasons) + '. ' if reasons else 'Sem gatilho de vídeo nesta verificação. '
    if near and not lightning['dados_atrasados']:
        text += f"Raio mais próximo a {near['km']} quilômetros, no setor {near['direcao']}. "
    if motion:
        text += f"Deslocamento estimado das células na região para {motion['para']}, a {motion['velocidade_kmh']} quilômetros por hora. "
    else:
        text += 'Direção de deslocamento não determinada com confiança. '
    text += ('O risco é regional; não confirma impacto em todos os bairros. ' + ' '.join(advice)
             + ' Inscreva-se no TROVOX TEMPO e ative o sino para receber alertas.')
    report = {'cidade': key, 'nome': name, 'uf': state, 'lat': lat, 'lon': lon,
            'verificado_em': now.isoformat() + 'Z', 'gerar': bool(reasons), 'motivos': reasons,
            'raios': lightning, 'nowcasting': point if valid else None, 'chuva': radar,
            'roteiro': text, 'recomendacoes': advice, 'raio_km': 40, 'aproximacao_chuva': incoming_rain}
    if key in SPANISH_CITIES:
        from .shorts_spanish import localize_report
        localize_report(report)
    return report


class Monitor:
    def __init__(self, resources, root):
        self.resources, self.root = resources, Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.lock = threading.Lock()
        self.stop = threading.Event()
        with self.db() as db:
            db.execute('CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, city TEXT, created REAL, payload TEXT)')
            # A process restart must not leave a video forever in rendering.
            for ident, payload in db.execute('SELECT id,payload FROM jobs').fetchall():
                item = json.loads(payload)
                if item['estado'] in ('fila', 'gerando'):
                    item.update(estado='falhou', erro='processo reiniciado; próxima verificação poderá tentar novamente')
                    db.execute('UPDATE jobs SET payload=? WHERE id=?', (json.dumps(item), ident))

    def db(self):
        return sqlite3.connect(self.root / 'shorts.sqlite3', timeout=30)

    def get(self, ident):
        with self.db() as db:
            row = db.execute('SELECT payload FROM jobs WHERE id=?', (ident,)).fetchone()
        return json.loads(row[0]) if row else None

    def save(self, item):
        with self.db() as db:
            db.execute('UPDATE jobs SET payload=? WHERE id=?', (json.dumps(item), item['id']))

    def eligible(self, key):
        seed = Path(__file__).resolve().parents[2] / 'templates/shorts-publications.json'
        if seed.exists():
            record = json.loads(seed.read_text()).get(key)
            if record:
                tz = ZoneInfo(city_timezone(key, CITIES[key][1]))
                published = datetime.fromisoformat(record['published_at'].replace('Z','+00:00'))
                if published.astimezone(tz).date() == datetime.now(tz).date():
                    return False
        tz = ZoneInfo(city_timezone(key, CITIES[key][1]))
        midnight = datetime.now(tz).replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
        with self.db() as db:
            rows = db.execute('SELECT created,payload FROM jobs WHERE city=?', (key,)).fetchall()
        return not any(json.loads(payload)['estado'] in ('fila','gerando') or
                       (created >= midnight and json.loads(payload)['estado'] == 'concluido')
                       for created,payload in rows)

    def check(self, reports=None):
        if not self.lock.acquire(blocking=False):
            return {'ocupado': True, 'resultados': []}
        try:
            results = []
            for key in (reports if reports is not None else CITIES):
                try:
                    if not self.eligible(key):
                        results.append({'cidade':key, 'suprimido':'aviso diário já reservado ou concluído'})
                        continue
                    report = reports[key] if reports is not None else evaluate(key, self.resources)
                    if reports is not None and (report.get('cidade') != key or
                                                not fresh(report.get('verificado_em'), utc_now())):
                        results.append({'cidade':key, 'erro':'alerta expirado antes da geração', 'gerar':False})
                        continue
                    if report['gerar']:
                        with self.db() as db:
                            tz = ZoneInfo(city_timezone(key, CITIES[key][1]))
                            now_local = datetime.now(tz)
                            midnight = now_local.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
                            recent = db.execute('SELECT payload FROM jobs WHERE city=? AND created>=?',
                                                (key, midnight)).fetchall()
                            pending = db.execute('SELECT payload FROM jobs WHERE city=?', (key,)).fetchall()
                            blocked = any(json.loads(r[0])['estado'] in ('fila', 'gerando') for r in pending)
                            blocked |= any(json.loads(r[0])['estado'] == 'concluido' for r in recent)
                            if not blocked:
                                item = {'id': uuid.uuid4().hex, 'estado': 'fila', 'alerta': report}
                                db.execute('INSERT INTO jobs VALUES (?,?,?,?)',
                                           (item['id'], key, datetime.now(timezone.utc).timestamp(), json.dumps(item)))
                                report['video_id'] = item['id']
                                threading.Thread(target=self.work, args=(item,), daemon=True).start()
                            else:
                                report['suprimido'] = 'vídeo pendente ou aviso já gerado hoje para esta cidade'
                    results.append(report)
                except Exception as exc:
                    results.append({'cidade': key, 'erro': str(exc), 'gerar': False})
            return {'resultados': results}
        finally:
            self.lock.release()

    def work(self, item, *, recheck=True):
        # One encoder at a time, including jobs dispatched by different monitoring passes.
        with self.render_lock:
            try:
                item['estado'] = 'gerando'
                self.save(item)
                latest = evaluate(item['alerta']['cidade'], self.resources) if recheck else item['alerta']
                if not latest['gerar'] or not fresh(latest['verificado_em'], utc_now()):
                    raise ValueError('alerta expirado antes da renderização')
                item['alerta'] = latest
                render(self.root / item['id'], latest, self.resources)
                item['estado'] = 'concluido'
                self.save(item)
                if os.environ.get('SHORTS_AUTO_PUBLISH', '').lower() == 'true':
                    try:
                        from .youtube import publish_short
                        item['youtube'] = publish_short(self.root / item['id'])
                    except Exception as exc:
                        item['youtube'] = {'error': str(exc)}
            except Exception as exc:
                item.update(estado='falhou', erro=str(exc))
            self.save(item)

    render_lock = threading.Lock()

    def start(self):
        import fcntl
        self._process_lock = (self.root / 'monitor.lock').open('a')
        try:
            fcntl.flock(self._process_lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            self._process_lock.close()
            raise RuntimeError('já existe um monitor de Shorts usando esta pasta')
        def loop():
            while not self.stop.is_set():
                self.check()
                self.stop.wait(1800)
        threading.Thread(target=loop, daemon=True, name='city-shorts-monitor').start()


def render(directory, report, resources):
    """Narrated vertical alert with local coordinate maps; no invented rain or motion."""
    import edge_tts
    import textwrap
    directory.mkdir(parents=True, exist_ok=True)
    # Expired alerts must never wait in the encoder queue and become new videos.
    if not fresh(report['verificado_em'], utc_now()):
        raise ValueError('alerta expirado na fila; aguarde nova verificação')
    (directory / 'alerta.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))
    asyncio.run(edge_tts.Communicate(report['roteiro'], report.get('voz', 'pt-BR-FranciscaNeural')).save(str(directory / 'voz.mp3')))
    lat, lon = report['lat'], report['lon']
    dx = 0.55 / np.cos(np.radians(lat)) * (620/420)
    west, east, south, north = lon - dx, lon + dx, lat - .55, lat + .55
    font = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', 25)
    from .regional_map import basemap, mercator
    region = basemap((west,east,south,north), directory.parent / 'map-tile-cache')
    region.save(directory / 'mapa-regional.png')
    def xy(y, x):
        return int(40 + (x-west)/(east-west)*640), int(400 + (mercator(north)-mercator(y))/(mercator(north)-mercator(south))*600)
    scenes = [('Risco de tempestade (estimativa)', 'risco'), ('Recomendações finais', 'fim')]
    if report['raios']['raios_40km'] and not report['raios']['dados_atrasados']:
        scenes.insert(0, ('Raios observados', 'raios'))
    for idx, (title, kind) in enumerate(scenes):
        image = Image.new('RGB', (720, 1280), '#101e32')
        draw = ImageDraw.Draw(image)
        def paragraph(text, y):
            for line in textwrap.wrap(text, 43):
                draw.text((35, y), line, font=font, fill='white'); y += 35
            return y
        paragraph(f"ALERTA NOWCASTING | {report['nome']} - {report['uf']}", 50)
        paragraph(report['verificado_em'] + ' | UTC', 155)
        paragraph(title, 235)
        if kind == 'fim':
            paragraph(' '.join(report['recomendacoes']), 400)
        else:
            image.paste(region, (40,400))
            draw.rectangle((40, 400, 680, 1000), outline='white')
            if kind == 'risco' and report['nowcasting']:
                import io
                import math
                meta = resources.json('/previsao/agora')
                if not any(fresh(meta.get(k), utc_now()) for k in ('raios_ate', 'nuvens_de', 'cod_de', 'meteo_de')):
                    raise ValueError('mapa de risco expirado')
                base = Image.open(io.BytesIO(resources.read('/previsao/agora.png'))).convert('RGBA')
                (bs, bw), (bn, be) = meta['limites']
                merc = lambda v: math.log(math.tan(math.pi/4 + math.radians(v)/2))
                x0, x1 = (west-bw)/(be-bw)*base.width, (east-bw)/(be-bw)*base.width
                y0 = (merc(bn)-merc(north))/(merc(bn)-merc(bs))*base.height
                y1 = (merc(bn)-merc(south))/(merc(bn)-merc(bs))*base.height
                tile = base.crop((int(x0),int(y0),int(x1)+1,int(y1)+1)).resize((640,600))
                tile.putalpha(tile.getchannel('A').point(lambda a: int(a * 0.42)))
                image.paste(tile, (40,400), tile)
            if kind == 'raios':
                flashes = resources.json('/observado/mapa')
                if not fresh(flashes.get('fim'), utc_now()):
                    raise ValueError('mapa de raios expirado')
                for y, x, count, unforecast, age in flashes['pontos']:
                    if age * flashes.get('idade_passo_min', 10) < 30 and south <= y <= north and west <= x <= east:
                        px,py = xy(y,x)
                        draw.ellipse((px-4,py-4,px+4,py+4), fill='#ffdf35', outline='#613f00', width=1)
            x,y = xy(lat,lon)
            draw.ellipse((x-8,y-8,x+8,y+8), outline='white', width=3)
            if kind == 'risco' and not report['nowcasting']:
                paragraph('Nowcasting indisponível', 650)
            paragraph('Centro da cidade | Norte acima', 1020)
            paragraph(f"Lat {south:.2f} a {north:.2f}; Lon {west:.2f} a {east:.2f}", 1090)
        paragraph('Risco: cinza sem sinal; amarelo baixo; laranja moderado; vermelho alto. Não é aviso oficial.', 1160)
        from .shorts_presenter import layout
        image = layout(image, report, title, kind)
        image.save(directory / f'{idx}.png')
    duration = float(subprocess.check_output(['ffprobe','-v','error','-show_entries','format=duration','-of','csv=p=0',str(directory/'voz.mp3')]))
    if duration > 60:
        raise ValueError('narração excedeu 60 segundos; vídeo não publicado')
    manifest = ''.join(f"file '{i}.png'\nduration {duration/len(scenes):.4f}\n" for i in range(len(scenes)))
    manifest += f"file '{len(scenes)-1}.png'\n"
    (directory/'frames.txt').write_text(manifest)
    from .shorts_presenter import synchronize
    print('Sincronizando apresentadora para o Short...', flush=True)
    presenter = synchronize(directory)
    subprocess.run(['ffmpeg','-y','-v','error','-f','concat','-safe','0','-i',str(directory/'frames.txt'),
                    '-i',str(directory/'voz.mp3'),'-i',str(presenter),
                    '-filter_complex', '[0:v]fps=25,setpts=PTS-STARTPTS[bg];[2:v]crop=trunc(iw*0.70/2)*2:trunc(ih*0.62/2)*2:(iw-ow)/2:ih*0.06,scale=240:360:force_original_aspect_ratio=increase,crop=240:360,setsar=1,fps=25,setpts=PTS-STARTPTS[p];[bg][p]overlay=445:805:shortest=1[v]',
                    '-map','[v]','-map','1:a','-c:v','libx264','-threads','2','-pix_fmt','yuv420p','-r','25',
                    '-c:a','aac','-shortest',str(directory/'short.mp4')], check=True, timeout=240)
