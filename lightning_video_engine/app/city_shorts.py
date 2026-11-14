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
from .sp_flood_shorts import SP_FLOOD_CITIES
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


def rain_duration(lat, lon, min_class=2):
    from .shorts_rain import rain_minutes_at
    return rain_minutes_at(lat, lon, min_class=min_class)


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

    def municipal_boundary(self, city, state):
        return self.json('/previsao/limite-municipal', nome=f'{city}, {state}, Brasil')


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
    'novo-horizonte': ('Novo Horizonte', 'SC', -26.444, -52.834),
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
    'maringa': ('Maringá', 'PR', -23.420, -51.933),
    'londrina': ('Londrina', 'PR', -23.304, -51.169),
    'chapeco': ('Chapecó', 'SC', -27.100, -52.615),
    **SP_FLOOD_CITIES,
}

# 13/11/2026: no Sul, o alerta deixou de ser por cidade e passou a ser por estado, com o nome da Região Sul.
# O monitor lê os raios em volta destas cidades de cada estado e o alerta parte da que tem mais raios;
# cada estado tem no máximo um alerta por dia (Monitor.eligible), como as cidades.
SOUTH_STATES = {
    'sul-pr': ('Paraná', 'PR', 'no'),
    'sul-sc': ('Santa Catarina', 'SC', 'em'),
    'sul-rs': ('Rio Grande do Sul', 'RS', 'no'),
}
SOUTH_POINTS = {
    'PR': [('Curitiba', -25.428, -49.273), ('Ponta Grossa', -25.095, -50.162), ('Guarapuava', -25.390, -51.465),
           ('Cascavel', -24.956, -53.455), ('Foz do Iguaçu', -25.548, -54.588), ('Maringá', -23.425, -51.939),
           ('Londrina', -23.310, -51.163), ('Umuarama', -23.766, -53.325), ('Francisco Beltrão', -26.081, -53.055),
           ('Paranaguá', -25.516, -48.525), ('Campo Mourão', -24.043, -52.379), ('Santo Antônio da Platina', -23.295, -50.077),
           ('União da Vitória', -26.230, -51.086), ('Pato Branco', -26.229, -52.671), ('Telêmaco Borba', -24.324, -50.616),
           ('Paranavaí', -23.073, -52.465)],
    'SC': [('Florianópolis', -27.597, -48.549), ('Joinville', -26.304, -48.846), ('Blumenau', -26.919, -49.066),
           ('Lages', -27.816, -50.326), ('Chapecó', -27.096, -52.618), ('Joaçaba', -27.178, -51.505),
           ('São Miguel do Oeste', -26.725, -53.518), ('Criciúma', -28.677, -49.370), ('Caçador', -26.775, -51.015),
           ('Mafra', -26.111, -49.805), ('Tubarão', -28.467, -49.007), ('Rio do Sul', -27.214, -49.643),
           ('Concórdia', -27.234, -52.028), ('Curitibanos', -27.283, -50.584), ('São Bento do Sul', -26.250, -49.379)],
    'RS': [('Porto Alegre', -30.033, -51.230), ('Caxias do Sul', -29.168, -51.179), ('Passo Fundo', -28.263, -52.407),
           ('Santa Maria', -29.684, -53.807), ('Pelotas', -31.770, -52.341), ('Uruguaiana', -29.755, -57.088),
           ('Santo Ângelo', -28.299, -54.263), ('Erechim', -27.635, -52.275), ('Bagé', -31.331, -54.107),
           ('Santa Rosa', -27.871, -54.481), ('Frederico Westphalen', -27.359, -53.394), ('Alegrete', -29.783, -55.792),
           ('Santa Cruz do Sul', -29.718, -52.426), ('Cruz Alta', -28.644, -53.606), ('Vacaria', -28.512, -50.934),
           ('Torres', -29.335, -49.727), ('Camaquã', -30.851, -51.812), ('São Borja', -28.661, -56.004),
           ('Santana do Livramento', -30.891, -55.532), ('Lajeado', -29.467, -51.961), ('Rio Grande', -32.035, -52.099),
           ('São Gabriel', -30.336, -54.320), ('Gramado', -29.379, -50.874)],
}


def place_state(key):
    """UF of a monitored key, city or southern state."""
    return SOUTH_STATES[key][1] if key in SOUTH_STATES else CITIES[key][1]

# Cidades que o monitor automático varre. CITIES continua sendo o catálogo completo (testes, scripts).
# 07/11/2026: comentadas as cidades cujo alerta não chegou a 500 visualizações no TROVOX TEMPO,
# ou que nunca geraram alerta. Descomente para voltar a monitorar.
MONITORED = [
    'rio-de-janeiro',
    # 'salvador',
    # 'florianopolis',  # 13/11/2026: o Sul passou a ter alerta por estado (sul-pr, sul-sc, sul-rs)
    # 'maceio',
    # 'gramado',
    'sao-paulo',  # 13/11/2026: só a capital, num raio de 25 km (RADIUS_KM); um alerta por dia
    # 'curitiba',
    # 'porto-alegre',
    # 'santa-maria',
    # 'novo-horizonte',
    # 'brasilia',
    # 'belo-horizonte',  # 13/11/2026: retirado a pedido
    'campo-grande',
    # 'manaus',
    # 'cordoba',
    # 'buenos-aires',
    # 'santa-cruz-de-la-sierra',
    # 'santiago',
    # 'bogota',
    'guayaquil',
    # 'asuncion',
    # 'lima',
    # 'montevideo',
    'caracas',
    # 'maringa',  # 10/11/2026: Região Sul (Norte do PR e Oeste de SC)
    # 'londrina',
    # 'chapeco',
    'sul-pr',  # 13/11/2026: alerta por estado da Região Sul (SOUTH_STATES)
    'sul-sc',
    'sul-rs',
    # *SP_FLOOD_CITIES,  # alagamento em SP: nenhum alerta passou de 500 visualizações
]


# Raio do alerta por cidade (km); as demais usam 40. A capital paulista usa 25 para não disparar
# com tempestades no interior ou no litoral.
RADIUS_KM = {'sao-paulo': 25}


def city_radius(key):
    return RADIUS_KM.get(key, 40)


def situation(resources, key, place=None):
    """/alertas/situacao for the city. With a custom radius, raios_40km is replaced by the count within
    that radius (raios_raio), or None when the API does not give it, so nothing claims a 40 km count."""
    _, _, lat, lon = place or CITIES[key]
    radius = city_radius(key)
    if radius == 40:
        return resources.json('/alertas/situacao', lat=lat, lon=lon)
    lightning = dict(resources.json('/alertas/situacao', lat=lat, lon=lon, raio_km=radius))
    count = lightning.get('raios_raio')
    lightning['raios_40km'] = count if isinstance(count, int) and not isinstance(count, bool) else None
    return lightning


def fresh(value, now):
    if not value:
        return False
    t = datetime.fromisoformat(value.replace('Z', '+00:00')).replace(tzinfo=None)
    return 0 <= (now - t).total_seconds() <= 900


def lightning_hook(lightning):
    """Strikes within the city's radius (40 km unless RADIUS_KM says otherwise) in the last 30 minutes, when the count is complete and current; None otherwise."""
    lightning = lightning or {}
    count = lightning.get('raios_40km')
    if lightning.get('dados_atrasados') or not isinstance(count, int) or isinstance(count, bool) or count < 1:
        return None
    return count


def lightning_observed_at(lightning):
    """Timestamp of a complete, fresh 30-minute lightning observation."""
    if lightning.get('dados_atrasados') or lightning.get('janela_incompleta', True) or not lightning.get('coberto'):
        return None
    try:
        observed = datetime.fromisoformat(lightning['dados_ate'].replace('Z', '+00:00'))
        if observed.tzinfo is None or not fresh(lightning['dados_ate'], utc_now()):
            return None
        return observed.timestamp()
    except (KeyError, TypeError, ValueError, AttributeError):
        return None


def evaluate(key, resources, *, lightning=None, density_reference=None, place=None, region=None):
    """place=(name, uf, lat, lon) evaluates a point outside CITIES; region=(state name, preposition,
    other places with lightning) opens the text as a Região Sul state alert."""
    name, state, lat, lon = place or CITIES[key]
    now = utc_now()
    radius = city_radius(key)
    lightning = lightning if lightning is not None else situation(resources, key, place)
    try:
        point = resources.json('/observado/ponto', lat=lat, lon=lon, raio_km=radius).get('agora')
    except (OSError, ValueError, KeyError, TypeError):
        point = None
    valid = point and any(fresh(point.get(k), now) for k in ('raios_ate', 'nuvens_de', 'cod_de', 'meteo_de'))
    try:
        radar = rain_at(lat, lon)
    except (OSError, ValueError, KeyError, TypeError):
        radar = None
    reasons = []
    radar_fresh = bool(radar and radar.get('coberto') and not radar.get('neve') and
                       radar.get('classe') is not None and radar.get('hora') is not None and
                       0 <= (now - datetime.fromtimestamp(radar['hora'], timezone.utc)
                             .replace(tzinfo=None)).total_seconds() <= 900)
    lightning_fresh = not lightning['dados_atrasados'] and lightning['coberto']
    near = lightning.get('mais_proximo')
    recent_lightning = bool(lightning_fresh and near and near.get('km', float('inf')) <= radius and
                            0 <= near.get('minutos_atras', float('inf')) <= 15)
    # Needs the radar's yellow: blue rain alone published "storm" alerts for drizzle. Where no
    # radar answers, radar_fresh is False and this rule stays silent; lightning rules still apply.
    try:
        persistent_rain_minutes = rain_duration(lat, lon, 2) if radar_fresh and radar['classe'] >= 2 else None
    except (OSError, ValueError, KeyError, TypeError):
        persistent_rain_minutes = None
    persistent_rain = bool(persistent_rain_minutes is not None and persistent_rain_minutes >= 10)
    flood_only = key in SP_FLOOD_CITIES
    if flood_only and persistent_rain:
        reasons.append('chuva forte persistente com potencial de alagamento no município')
    if not flood_only and radar_fresh and recent_lightning:
        reasons.append('chuva detectada no radar e raios recentes na região')
    if not flood_only and radar_fresh and persistent_rain:
        reasons.append('chuva forte persistente na escala do radar na área monitorada')
    # A single fresh, intense local lightning observation is sufficient: a
    # prior scan may be unavailable after a scheduled-run delay.
    close_count = lightning.get('raios_15km')
    intense_lightning = bool(recent_lightning and isinstance(close_count, int) and close_count >= 10 and
                             near.get('km', float('inf')) <= 15 and near.get('minutos_atras', float('inf')) <= 10)
    if not flood_only and intense_lightning:
        reasons.append(f'atividade elétrica intensa: {close_count} raios observados em até 15 quilômetros')
    density = None
    current_at = lightning_observed_at(lightning)
    if not flood_only and density_reference and current_at is not None:
        elapsed = (current_at - density_reference['observed_at']) / 60
        before = density_reference['count_15']
        current = lightning.get('raios_15km')
        if (5 <= elapsed <= 30 and isinstance(current, int) and 0 <= before and
                current >= 10 and current - before >= 8 and current >= 2 * max(before, 1) and
                near and near.get('km', float('inf')) <= 15 and
                0 <= near.get('minutos_atras', float('inf')) <= 10):
            density = {'antes_15km': before, 'agora_15km': current,
                       'intervalo_min': round(elapsed), 'janela_min': 30}
            if not reasons:
                reasons.append(f'A atividade elétrica aumentou de {before} para {current} raios '
                               'na área de 15 quilômetros, na janela móvel de 30 minutos')
    try:
        incoming_rain = rain_approach(lat, lon) if reasons else None
    except (OSError, ValueError, KeyError, TypeError):
        incoming_rain = None
    advice = ['Não atravesse vias alagadas nem áreas com correnteza.',
              'Evite pontos baixos e acompanhe os avisos da Defesa Civil.'] if flood_only else ['Procure abrigo em uma edificação ou veículo fechado.',
              'Evite áreas abertas, árvores isoladas e atividades na água.',
              'Não atravesse ruas alagadas. Acompanhe os avisos da Defesa Civil.']
    motion = point.get('deslocamento') if valid else None
    hook = lightning_hook(lightning)
    if flood_only:
        text = f"Atenção, {name}, {state}. Alerta preventivo de potencial de alagamento no município. "
    elif region and hook:
        text = f"{hook} raios em 30 minutos perto de {name}, {region[1]} {region[0]}! Alerta de tempestade na Região Sul. "
    elif region:
        text = f"Alerta de tempestade na Região Sul: {name}, {region[1]} {region[0]}. "
    elif hook:
        # The striking number comes first: most viewers decide in the first two seconds.
        text = f"{hook} raios em 30 minutos a até {radius} quilômetros de {name}! Atenção, {state}. "
    else:
        text = f"Atenção, {name}, {state}. Monitoramento da área até {radius} quilômetros do centro. "
    text += '; '.join(reasons) + '. ' if reasons else ''
    if region and region[2]:
        others = list(region[2])
        text += 'Também há raios perto de ' + (', '.join(others[:-1]) + ' e ' + others[-1] if len(others) > 1 else others[0]) + '. '
    if not flood_only and near and not lightning['dados_atrasados']:
        text += f"Raio mais próximo a {near['km']} quilômetros, no setor {near['direcao']}. "
    if motion and not flood_only:
        text += f"Deslocamento estimado das células na região para {motion['para']}, a {motion['velocidade_kmh']} quilômetros por hora. "
    else:
        text += 'Direção de deslocamento não determinada com confiança. '
    if flood_only:
        text += 'O risco é localizado; não confirma alagamento em todo o município nem em todos os bairros. '
    text += (' '.join(advice) + ' Choveu forte aí? Conte nos comentários. '
             'E inscreva-se no TROVOX TEMPO para receber o próximo alerta antes da tempestade chegar.')
    report = {'cidade': key, 'nome': name, 'uf': state, 'lat': lat, 'lon': lon,
            'verificado_em': now.isoformat() + 'Z', 'gerar': bool(reasons), 'motivos': reasons,
            'raios': lightning, 'nowcasting': point if valid else None, 'chuva': radar,
            'roteiro': text, 'recomendacoes': advice, 'raio_km': radius,
            'aproximacao_chuva': incoming_rain, 'densidade': density,
            'secao': 'alagamentos-sp' if flood_only else 'nowcasting'}
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
            db.execute('CREATE TABLE IF NOT EXISTS lightning_samples '
                       '(city TEXT, observed_at REAL, count_15 INTEGER, PRIMARY KEY(city, observed_at))')
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

    def evaluate_city(self, key):
        if key in SOUTH_STATES:
            return self.evaluate_state(key)
        return self.evaluate_point(key)

    def evaluate_state(self, key):
        """A Região Sul state alert from the point of the state with the most lightning within 40 km."""
        from concurrent.futures import ThreadPoolExecutor
        state_name, uf, preposition = SOUTH_STATES[key]
        points = [(name, uf, lat, lon) for name, lat, lon in SOUTH_POINTS[uf]]

        def read(place):
            try:
                return situation(self.resources, key, place)
            except (OSError, ValueError, KeyError, TypeError):
                return None
        with ThreadPoolExecutor(6, thread_name_prefix='south-scan') as pool:
            readings = list(zip(points, pool.map(read, points)))
        active = sorted(((place, lightning) for place, lightning in readings if lightning_hook(lightning)),
                        key=lambda item: -lightning_hook(item[1]))
        report = None
        # The three points with the most lightning are tried in turn: the radar may cancel one of them.
        for place, lightning in active[:3] or [(points[0], None)]:
            others = [other[0] for other, _ in active if other is not place][:2]
            report = self.evaluate_point(key, place=place, lightning=lightning,
                                         region=(state_name, preposition, others), sample=f'{key}:{place[0]}')
            if report['gerar']:
                break
        report.update(cidade=key, regiao='Região Sul', estado_nome=state_name,
                      titulo_tela=f'{state_name} • Região Sul',
                      lugar_titulo=f"{preposition} {state_name}, perto de {report['nome']}",
                      titulo_sem_raios=f'{state_name}, Região Sul')
        return report

    def evaluate_point(self, key, *, place=None, lightning=None, region=None, sample=None):
        sample = sample or key
        lightning = lightning if lightning is not None else situation(self.resources, key, place)
        observed_at = lightning_observed_at(lightning)
        reference = None
        if observed_at is not None:
            with self.db() as db:
                row = db.execute('SELECT observed_at,count_15 FROM lightning_samples '
                                 'WHERE city=? AND observed_at BETWEEN ? AND ? '
                                 'ORDER BY observed_at DESC LIMIT 1',
                                 (sample, observed_at - 1800, observed_at - 300)).fetchone()
            if row:
                reference = {'observed_at': row[0], 'count_15': row[1]}
        report = evaluate(key, self.resources, lightning=lightning, density_reference=reference, place=place, region=region)
        current = lightning.get('raios_15km')
        if observed_at is not None and isinstance(current, int) and current >= 0:
            with self.db() as db:
                db.execute('INSERT OR IGNORE INTO lightning_samples VALUES (?,?,?)',
                           (sample, observed_at, current))
                db.execute('DELETE FROM lightning_samples WHERE observed_at<?',
                           (datetime.now(timezone.utc).timestamp() - 7200,))
        return report

    def eligible(self, key):
        if key in SP_FLOOD_CITIES:
            return True
        seed = Path(__file__).resolve().parents[2] / 'templates/shorts-publications.json'
        if seed.exists():
            record = json.loads(seed.read_text()).get(key)
            if record:
                tz = ZoneInfo(city_timezone(key, place_state(key)))
                published = datetime.fromisoformat(record['published_at'].replace('Z','+00:00'))
                if published.astimezone(tz).date() == datetime.now(tz).date():
                    return False
        tz = ZoneInfo(city_timezone(key, place_state(key)))
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
            for key in (reports if reports is not None else MONITORED):
                try:
                    if not self.eligible(key):
                        results.append({'cidade':key, 'suprimido':'aviso diário já reservado ou concluído'})
                        continue
                    report = reports[key] if reports is not None else self.evaluate_city(key)
                    if reports is not None and (report.get('cidade') != key or
                                                not fresh(report.get('verificado_em'), utc_now())):
                        results.append({'cidade':key, 'erro':'alerta expirado antes da geração', 'gerar':False})
                        continue
                    if report['gerar']:
                        with self.db() as db:
                            tz = ZoneInfo(city_timezone(key, place_state(key)))
                            now_local = datetime.now(tz)
                            midnight = now_local.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
                            recent = db.execute('SELECT payload FROM jobs WHERE city=? AND created>=?',
                                                (key, midnight)).fetchall()
                            pending = db.execute('SELECT payload FROM jobs WHERE city=?', (key,)).fetchall()
                            if key in SP_FLOOD_CITIES:
                                zone=report.get('zona_id')
                                daily=[json.loads(r[0]) for r in recent]
                                used={x.get('alerta',{}).get('zona_id') for x in daily if x.get('alerta',{}).get('zona_id')}
                                pending_zones={json.loads(r[0]).get('alerta',{}).get('zona_id') for r in pending if json.loads(r[0])['estado'] in ('fila','gerando')}
                                # A polygon's shape changes between scans, so the limit is per city, not per shape.
                                from .sp_flood_zones import MAX_DAILY_SHORTS_PER_CITY
                                blocked=not zone or bool(pending_zones) or len(used) >= MAX_DAILY_SHORTS_PER_CITY
                                if blocked: report['suprimido']='sem área confirmada ou alerta de alagamento já emitido hoje para a cidade'
                            else:
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

    def work(self, item, *, recheck=False):
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
                    from .instagram import cross_post
                    from .youtube import QuotaExceeded, block_quota, publish_short
                    try:
                        item['youtube'] = publish_short(self.root / item['id'])
                        if (instagram := cross_post(self.root / item['id'])) is not None:
                            item['instagram'] = instagram
                    except QuotaExceeded as exc:
                        block_quota(self.root, str(exc))
                        item['youtube'] = {'error': str(exc), 'quota': True}
                        # Instagram still gets the alert; only when it also fails is the city retried.
                        instagram = cross_post(self.root / item['id'])
                        if instagram is not None:
                            item['instagram'] = instagram
                        if not instagram or instagram.get('error'):
                            item.update(estado='falhou', erro=f'upload: {exc}')
                    except Exception as exc:
                        # An unpublished alert must not reserve the city for the rest of the day.
                        item.update(estado='falhou', erro=f'upload: {exc}', youtube={'error': str(exc)})
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
    asyncio.run(asyncio.wait_for(edge_tts.Communicate(report['roteiro'], report.get('voz', 'pt-BR-FranciscaNeural'))
                                 .save(str(directory / 'voz.mp3')), timeout=120))
    try:
        from .alert_clouds import render_clouds
        render_clouds(directory, report, resources)
        return
    except Exception as exc:
        print('Nuvens em movimento indisponíveis; usando o layout estático:', exc, flush=True)
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
