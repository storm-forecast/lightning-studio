"""Daily South America bulletin: maximum temperature, minimum humidity, storms and health risk.

Everything said and drawn is computed from the day's forecast files: nothing is hand-written per day.
A missing source raises, so a day without data produces no video instead of a video without data.
Key frames of the clouds are observed GOES-19 images; the frames between them are computed.
"""
import asyncio
import concurrent.futures
import csv
import glob
import gzip
import json
import math
import re
import shutil
import subprocess
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[2]
ASSETS = ROOT / 'templates/america-do-sul'
RELEASE = 'https://github.com/storm-forecast/lightning-data-prediction/releases/download/latest'
ECMWF = 'https://data.ecmwf.int/forecasts/{run:%Y%m%d}/{run:%H}z/ifs/0p25/oper/{run:%Y%m%d%H}0000-{step}h-oper-fc'
GIBS = ('https://gibs.earthdata.nasa.gov/wms/epsg4326/best/wms.cgi?SERVICE=WMS&VERSION=1.3.0&REQUEST=GetMap'
        '&LAYERS=GOES-East_ABI_GeoColor&STYLES=&CRS=EPSG:4326&BBOX=-46,-90,16,-24&WIDTH=2112&HEIGHT=1984'
        '&FORMAT=image/jpeg&TIME={time:%Y-%m-%dT%H:%M:00Z}')
BRT = ZoneInfo('America/Sao_Paulo')
W, H, FPS, MW, S2 = 1920, 1080, 25, 1180, 2
GRID_W, GRID_N, GRID_E, GRID_S = -86, 14, -33, -57
RES = .25
HOT, VERY_HOT, DRY_ATTENTION, DRY_ALERT, DRY_EMERGENCY = 38, 40, 30, 20, 12
STORM_PROB, STORM_RAIN = .45, 5
UF = {'Acre': 'AC', 'Alagoas': 'AL', 'Amapá': 'AP', 'Amazonas': 'AM', 'Bahia': 'BA', 'Ceará': 'CE', 'Distrito Federal': 'DF',
      'Espírito Santo': 'ES', 'Goiás': 'GO', 'Maranhão': 'MA', 'Mato Grosso': 'MT', 'Mato Grosso do Sul': 'MS', 'Minas Gerais': 'MG',
      'Pará': 'PA', 'Paraíba': 'PB', 'Paraná': 'PR', 'Pernambuco': 'PE', 'Piauí': 'PI', 'Rio de Janeiro': 'RJ',
      'Rio Grande do Norte': 'RN', 'Rio Grande do Sul': 'RS', 'Rondônia': 'RO', 'Roraima': 'RR', 'Santa Catarina': 'SC',
      'São Paulo': 'SP', 'Sergipe': 'SE', 'Tocantins': 'TO'}
IN_STATE = {'Acre': 'no Acre', 'Alagoas': 'em Alagoas', 'Amapá': 'no Amapá', 'Amazonas': 'no Amazonas', 'Bahia': 'na Bahia', 'Ceará': 'no Ceará',
            'Distrito Federal': 'no Distrito Federal', 'Espírito Santo': 'no Espírito Santo', 'Goiás': 'em Goiás', 'Maranhão': 'no Maranhão',
            'Mato Grosso': 'em Mato Grosso', 'Mato Grosso do Sul': 'em Mato Grosso do Sul', 'Minas Gerais': 'em Minas Gerais', 'Pará': 'no Pará',
            'Paraíba': 'na Paraíba', 'Paraná': 'no Paraná', 'Pernambuco': 'em Pernambuco', 'Piauí': 'no Piauí', 'Rio de Janeiro': 'no Rio de Janeiro',
            'Rio Grande do Norte': 'no Rio Grande do Norte', 'Rio Grande do Sul': 'no Rio Grande do Sul', 'Rondônia': 'em Rondônia', 'Roraima': 'em Roraima',
            'Santa Catarina': 'em Santa Catarina', 'São Paulo': 'em São Paulo', 'Sergipe': 'em Sergipe', 'Tocantins': 'no Tocantins'}
IN_COUNTRY = {'Argentina': 'na Argentina', 'Bolívia': 'na Bolívia', 'Chile': 'no Chile', 'Colômbia': 'na Colômbia', 'Equador': 'no Equador', 'Guiana': 'na Guiana',
              'Paraguai': 'no Paraguai', 'Peru': 'no Peru', 'Suriname': 'no Suriname', 'Uruguai': 'no Uruguai', 'Venezuela': 'na Venezuela'}
CC = {'Argentina': 'AR', 'Bolívia': 'BO', 'Chile': 'CL', 'Colômbia': 'CO', 'Equador': 'EC', 'Guiana': 'GY', 'Paraguai': 'PY', 'Peru': 'PE', 'Suriname': 'SR', 'Uruguai': 'UY',
      'Venezuela': 'VE', 'Brasil': 'BR'}
MACRO = {'Norte': ['Acre', 'Amapá', 'Amazonas', 'Pará', 'Rondônia', 'Roraima', 'Tocantins'],
         'Nordeste': ['Alagoas', 'Bahia', 'Ceará', 'Maranhão', 'Paraíba', 'Pernambuco', 'Piauí', 'Rio Grande do Norte', 'Sergipe'],
         'Centro-Oeste': ['Distrito Federal', 'Goiás', 'Mato Grosso', 'Mato Grosso do Sul'],
         'Sudeste': ['Espírito Santo', 'Minas Gerais', 'Rio de Janeiro', 'São Paulo'], 'Sul': ['Paraná', 'Rio Grande do Sul', 'Santa Catarina']}
NUMBER_ORDER = ('abertura', 'panorama', 'hoje', 'amanha', 'calor', 'umidade', 'saude', 'regioes', 'paises', 'fim')


def humidity(temperature, dew_point):
    magnus = lambda x: np.exp(17.625 * x / (243.04 + x))
    return np.clip(100 * magnus(dew_point) / magnus(temperature), 0, 100)


def forecast_days(now):
    """Today and tomorrow in Brasília, as (label, first and last UTC instants of each day)."""
    local = now.astimezone(BRT).replace(hour=0, minute=0, second=0, microsecond=0)
    return [(day.date(), day.astimezone(timezone.utc).replace(tzinfo=None), (day + timedelta(days=1)).astimezone(timezone.utc).replace(tzinfo=None))
            for day in (local, local + timedelta(days=1))]


def lightning_windows(day):
    """The UTC six-hour windows closest to one Brasília day, the same the alerts and maps use."""
    midnight = datetime(day.year, day.month, day.day)
    return [midnight + timedelta(hours=h) for h in (6, 12, 18, 24)]


def get(url, headers=None, timeout=120):
    request = urllib.request.Request(url, headers={'User-Agent': 'trovox-tempo', **(headers or {})})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


def fetch_release(work):
    for name in ('ecens_prediction_ALL_regions_suavisado.nc', 'ecens_precipitation_global.nc'):
        path = work / name
        if not path.exists():
            path.write_bytes(get(f'{RELEASE}/{name}', timeout=300))
    return work / 'ecens_prediction_ALL_regions_suavisado.nc', work / 'ecens_precipitation_global.nc'


def latest_ecmwf_run(now):
    """The newest run already published; today's 00 UTC arrives some hours after it starts."""
    clock = now.astimezone(timezone.utc).replace(tzinfo=None, minute=0, second=0, microsecond=0)
    for back in range(0, 49):
        run = clock - timedelta(hours=back)
        if run.hour not in (0, 12):
            continue
        try:
            get(ECMWF.format(run=run, step=48) + '.index', timeout=30)
            return run
        except OSError:
            continue
    raise RuntimeError('rodada do ECMWF indisponível')


def ecmwf_field(run, step, param, work):
    """One surface field, cropped to the continent, from its byte range in the published file."""
    binary = work / f'{param}_{step:03d}.bin'
    if not binary.exists():
        base = ECMWF.format(run=run, step=step)
        rows = [json.loads(line) for line in get(base + '.index', timeout=60).decode().splitlines()]
        item = next(row for row in rows if row['param'] == param)
        grib = binary.with_suffix('.grib2')
        grib.write_bytes(get(base + '.grib2', {'Range': f"bytes={item['_offset']}-{item['_offset'] + item['_length'] - 1}"}))
        subprocess.run(['gdal_translate', '-q', '--config', 'GRIB_NORMALIZE_UNITS', 'YES', '-projwin', str(GRID_W), str(GRID_N), str(GRID_E), str(GRID_S), '-of', 'ENVI', '-ot', 'Float32',
                        str(grib), str(binary)], check=True, stderr=subprocess.DEVNULL)
    header = binary.with_suffix('.hdr').read_text()
    size = lambda key: int(re.search(rf'{key}\s*=\s*(\d+)', header)[1])
    return np.fromfile(binary, '<f4').reshape(size('lines'), size('samples'))


def nc_times(file):
    units = file['time'].attrs['units'].decode()
    base = datetime.fromisoformat(units.split('since ')[1])
    return [base + timedelta(hours=float(x)) for x in file['time'][()]]


def load_fields(now, target, work):
    """`target` names today and tomorrow: a render may start hours before its publication."""
    import h5py
    run = latest_ecmwf_run(now)
    days = forecast_days(target)
    jobs = {}
    for _, start, end in days:
        moment = start + timedelta(hours=3)
        while moment <= end:
            step = int((moment - run).total_seconds() // 3600)
            if step > 0:
                jobs[step] = None
            moment += timedelta(hours=3)
    if max(jobs) > 144:
        raise RuntimeError('rodada do ECMWF antiga demais')
    with concurrent.futures.ThreadPoolExecutor(5) as pool:
        for param in ('mx2t3', '2t', '2d'):
            list(pool.map(lambda step: ecmwf_field(run, step, param, work), jobs))
    sample = ecmwf_field(run, next(iter(jobs)), '2t', work)
    glat = 14.125 - RES * (np.arange(sample.shape[0]) + .5)
    glon = -86.125 + RES * (np.arange(sample.shape[1]) + .5)
    fields = {'glat': glat, 'glon': glon}
    prediction, rain = fetch_release(work)
    with h5py.File(prediction, 'r') as p, h5py.File(rain, 'r') as r:
        probability_times, rain_times = nc_times(p), nc_times(r)
        lat, lon, rain_lat, rain_lon = p['lat'][()], p['lon'][()], r['lat'][()], r['lon'][()]
        rain_lon = ((rain_lon + 180) % 360) - 180
        rain_j, rain_i = (np.abs(rain_lat[None, :] - glat[:, None]).argmin(1), np.abs(rain_lon[None, :] - glon[:, None]).argmin(1))
        prob_j, prob_i = (np.abs(lat[None, :] - glat[:, None]).argmin(1), np.abs(lon[None, :] - glon[:, None]).argmin(1))
        inside = (glat >= lat.min()) & (glat <= lat.max())
        for key, (label, start, end) in zip(('hoje', 'amanha'), days):
            steps = [s for s in jobs if start < run + timedelta(hours=s) <= end]
            if len(steps) < 5:
                raise RuntimeError(f'ECMWF incompleto para {label}')
            fields[key + '_tmax'] = np.max([ecmwf_field(run, s, 'mx2t3', work) for s in steps], 0)
            if not 20 < float(fields[key + '_tmax'].max()) < 60:
                raise RuntimeError('temperatura do ECMWF fora do esperado')
            fields[key + '_rh'] = np.min([humidity(ecmwf_field(run, s, '2t', work), ecmwf_field(run, s, '2d', work)) for s in steps], 0)
            windows = [w for w in lightning_windows(label) if w in probability_times and w in rain_times]
            if len(windows) < 3:
                raise RuntimeError(f'previsão de raios e chuva incompleta para {label}')
            probability = np.nanmax([p['prob-flash-ifs'][probability_times.index(w)] for w in windows], 0)
            total = np.sum([r['precip_6h'][rain_times.index(w)] for w in windows], 0)
            fields[key + '_rain'] = total[rain_j[:, None], rain_i[None, :]].astype(np.float32)
            gridded = probability[prob_j[:, None], prob_i[None, :]].astype(np.float32)
            gridded[~inside, :] = np.nan
            fields[key + '_prob'] = gridded
    fields['run'] = run
    fields['days'] = [str(day[0]) for day in days]
    return fields


def rasterize(rings, shape, lat0=14.125, lon0=-86.125, factor=4):
    height, width = shape
    image = Image.new('L', (width * factor, height * factor), 0)
    draw = ImageDraw.Draw(image)
    for ring in rings:
        draw.polygon([((x - lon0) / RES * factor, (lat0 - y) / RES * factor) for x, y in ring], fill=255)
    return np.asarray(image.resize((width, height), Image.BOX), float) / 255 >= .5


def regional_table(fields, outlines, places):
    shape = fields['glat'].shape + fields['glon'].shape
    table = {}
    masks = {'pais:' + c['nome']: rasterize(c['aneis'], shape) for c in outlines['paises'] if c['sul_americano']}
    masks.update({'uf:' + s['nome']: rasterize(s['aneis'], shape) for s in outlines['estados']})
    fields['land'] = np.any([m for key, m in masks.items() if key.startswith('pais:')], 0)
    for key, mask in masks.items():
        kind, name = key.split(':')
        here = [p for p in places if p[3] == 'BR' and p[4] == name] if kind == 'uf' else [p for p in places if p[3] == CC.get(name)]
        row = {}
        for day in ('hoje', 'amanha'):
            tmax, rh, rain, prob = [fields[f'{day}_{v}'] for v in ('tmax', 'rh', 'rain', 'prob')]
            def peak(values, largest=True):
                pick = np.nanargmax(np.where(mask, values, -999)) if largest else np.nanargmin(np.where(mask, values, 999))
                j, i = np.unravel_index(pick, values.shape)
                return float(values[j, i]), float(fields['glat'][j]), float(fields['glon'][i])
            t_value, t_lat, t_lon = peak(tmax)
            h_value, h_lat, h_lon = peak(rh, False)
            r_value, r_lat, r_lon = peak(rain)
            storm_area = mask & (prob >= STORM_PROB) & (rain >= STORM_RAIN)
            high = mask & (prob >= STORM_PROB)
            row[day] = {'tmax': round(t_value, 1), 'tmax_em': place_near(t_lat, t_lon, here), 'tmax_lat': t_lat, 'tmax_lon': t_lon,
                        'rh': round(h_value), 'rh_em': place_near(h_lat, h_lon, here), 'rh_lat': h_lat, 'rh_lon': h_lon,
                        'chuva': round(r_value), 'chuva_em': place_near(r_lat, r_lon, here), 'chuva_lat': r_lat, 'chuva_lon': r_lon,
                        'acima38': round(100 * float((tmax[mask] >= HOT).mean())), 'acima35': round(100 * float((tmax[mask] >= 35).mean())),
                        'abaixo30': round(100 * float((rh[mask] < DRY_ATTENTION).mean())), 'abaixo20': round(100 * float((rh[mask] < DRY_ALERT).mean())),
                        'perigo': round(100 * float(((tmax[mask] >= VERY_HOT) | (rh[mask] < DRY_EMERGENCY)).mean())),
                        'atencao': round(100 * float(((tmax[mask] >= HOT) | (rh[mask] < DRY_ALERT)).mean())),
                        'alta': round(100 * float(np.nan_to_num(prob[mask] >= STORM_PROB).mean())),
                        'tempestade': round(100 * float(storm_area[mask].mean())),
                        'alta_seca': int((high & (rain < 1)).sum()), 'alta_total': int(high.sum())}
        table[key] = row
    return table


def place_near(lat, lon, places, radius=45):
    """The largest town near a peak and inside the same state or country, or None: a name must be true."""
    if not places:
        return None
    array = np.array([(p[0], p[1]) for p in places])
    distance = np.hypot(array[:, 0] - lat, (array[:, 1] - lon) * math.cos(math.radians(lat))) * 111.2
    near = np.where(distance <= radius)[0]
    if not len(near):
        return None
    return places[max(near, key=lambda k: places[k][5])][2]


def load_places():
    rows = []
    with gzip.open(ASSETS / 'lugares.csv.gz', 'rt') as file:
        for row in csv.DictReader(file):
            rows.append((float(row['lat']), float(row['lon']), row['nome'], row['pais'], row['uf'], int(row['pop'])))
    return rows


def states(table, day, key, minimum=None, top=3, reverse=True):
    rows = [(name[3:], row[day]) for name, row in table.items() if name.startswith('uf:')]
    rows.sort(key=lambda item: item[1][key], reverse=reverse)
    if minimum is not None:
        rows = [r for r in rows if (r[1][key] >= minimum if reverse else r[1][key] <= minimum)]
    return rows[:top]


def joined(items):
    items = list(items)
    if len(items) <= 1:
        return ''.join(items)
    return ', '.join(items[:-1]) + ' e ' + items[-1]


def where(name, row, field):
    place = row[field + '_em']
    return f'na região de {place}, {IN_STATE[name]}' if place else IN_STATE[name]


def macro_row(table, day):
    out = {}
    for macro, members in MACRO.items():
        rows = [table['uf:' + m][day] for m in members]
        out[macro] = {'tmax': max(r['tmax'] for r in rows), 'rh': min(r['rh'] for r in rows), 'chuva': max(r['chuva'] for r in rows),
                      'acima38': sum(r['acima38'] for r in rows) / len(rows), 'abaixo30': sum(r['abaixo30'] for r in rows) / len(rows),
                      'tempestade': sum(r['tempestade'] for r in rows) / len(rows),
                      'tmax_uf': max(members, key=lambda m: table['uf:' + m][day]['tmax']), 'rh_uf': min(members, key=lambda m: table['uf:' + m][day]['rh']),
                      'chuva_uf': max(members, key=lambda m: table['uf:' + m][day]['chuva'])}
    return out


def first_upper(value):
    return value[:1].upper() + value[1:]


def date_words(day):
    return f'{day.day} de {("janeiro fevereiro março abril maio junho julho agosto setembro outubro novembro dezembro").split()[day.month - 1]}'


def write_narration(table, today, tomorrow):
    """The whole script, from numbers only. It must read correctly on a calm day as on an extreme one."""
    sentences = {}
    brazil = table['pais:Brasil']
    macros = {day: macro_row(table, day) for day in ('hoje', 'amanha')}
    hot_macro = max(macros['amanha'], key=lambda m: macros['amanha'][m]['acima38'])
    storm_macro = max(macros['amanha'], key=lambda m: macros['amanha'][m]['tempestade'])
    sentences['abertura'] = (f'Olá! Este é o boletim da Trovox Tempo, com a previsão para hoje, {date_words(today)}, e amanhã, {date_words(tomorrow)}, na América do Sul, '
                             'com foco no Brasil. Todos os dias, falamos aqui de três assuntos: o calor, a umidade do ar e as tempestades. '
                             'E mostramos onde o tempo pode ser perigoso para a sua saúde.')
    sentences['panorama'] = (f'Estas são imagens reais do satélite GOES-19, das últimas horas. Olhando para amanhã, o maior calor está no {hot_macro}, com máximas de até '
                             f'{macros["amanha"][hot_macro]["tmax"]:.0f} graus. Já as tempestades mais organizadas aparecem no {storm_macro}. Vamos ver cada ponto no mapa.')

    def storm_text(day, label):
        rows = states(table, day, 'tempestade', 5)
        rain = states(table, day, 'chuva', top=3)
        text = (f'Agora, as tempestades de {label}. O azul é a chuva prevista em vinte e quatro horas. A linha vermelha mostra onde o modelo da Trovox marca risco alto de raios. '
                'E o roxo mostra onde os dois se encontram: é onde a tempestade é mais provável. ')
        if rows:
            text += 'Os estados com a maior área nessa condição são ' + joined(f'{name}, com {row["tempestade"]} por cento do território' for name, row in rows) + '. '
        else:
            text += 'Nenhum estado tem área grande com raios e chuva juntos. '
        text += 'Os maiores volumes de chuva estão ' + joined(f'{where(name, row, "chuva")}, com cerca de {row["chuva"]} milímetros' for name, row in rain) + '. '
        if rain and rain[0][1]['chuva'] >= 50:
            text += 'Com esses volumes, pode haver alagamentos e deslizamentos. Por isso, acompanhe os avisos da Defesa Civil. '
        dry = brazil[day]['alta_seca'] / max(brazil[day]['alta_total'], 1)
        if dry >= .25:
            text += (f'Um ponto importante: em cerca de {round(dry * 100)} por cento da área de risco alto de raios, o modelo de chuva mostra menos de um milímetro. '
                     'Nessas áreas, a nossa confiança é menor, e as pancadas podem ser isoladas, ou nem acontecer.')
        return text
    sentences['hoje'] = storm_text('hoje', 'hoje')
    sentences['amanha'] = storm_text('amanha', 'amanhã')

    hot_today, hot_tomorrow = states(table, 'hoje', 'tmax'), states(table, 'amanha', 'tmax')
    share = states(table, 'amanha', 'acima38', 20, top=1)
    trend = brazil['amanha']['acima38'] - brazil['hoje']['acima38']
    trend_text = ('aumenta' if trend >= 2 else 'diminui' if trend <= -2 else 'fica parecida')
    sentences['calor'] = ('Agora, o calor. Este é o mapa da temperatura máxima prevista. Hoje, os pontos mais quentes do Brasil estão '
                          + joined(f'{where(n, r, "tmax")}, com {r["tmax"]:.0f} graus' for n, r in hot_today)
                          + '. Amanhã, os maiores valores estão ' + joined(f'{where(n, r, "tmax")}, com {r["tmax"]:.0f} graus' for n, r in hot_tomorrow) + '. '
                          + (f'{first_upper(IN_STATE[share[0][0]])}, {share[0][1]["acima38"]} por cento do território passa dos trinta e oito graus amanhã. ' if share else '')
                          + f'A tendência: a área do Brasil acima de trinta e oito graus {trend_text} de hoje para amanhã, de {brazil["hoje"]["acima38"]} para {brazil["amanha"]["acima38"]} por cento.')
    dry_today, dry_tomorrow = states(table, 'hoje', 'rh', reverse=False), states(table, 'amanha', 'rh', reverse=False)
    dry_share = states(table, 'amanha', 'abaixo30', 20, top=2)
    change = brazil['amanha']['abaixo30'] - brazil['hoje']['abaixo30']
    change_text = 'aumenta' if change >= 2 else 'diminui' if change <= -2 else 'fica parecida'
    sentences['umidade'] = ('Junto com o calor, vem o ar seco. Este é o mapa da umidade mínima. Para ler o mapa, use estas faixas: abaixo de trinta por cento, é estado de atenção. '
                            'Abaixo de vinte, é alerta. E abaixo de doze, é emergência. Hoje, a umidade mais baixa do Brasil aparece '
                            + joined(f'{where(n, r, "rh")}, com {r["rh"]} por cento' for n, r in dry_today)
                            + '. Amanhã, os menores valores estão ' + joined(f'{where(n, r, "rh")}, com {r["rh"]} por cento' for n, r in dry_tomorrow) + '. '
                            + ('Amanhã, ficam abaixo de trinta por cento de umidade ' + joined(f'{r["abaixo30"]} por cento do território {IN_STATE[n]}' for n, r in dry_share) + '. ' if dry_share else '')
                            + f'A tendência: a área seca no Brasil {change_text} de hoje para amanhã, de {brazil["hoje"]["abaixo30"]} para {brazil["amanha"]["abaixo30"]} por cento.')
    danger = states(table, 'amanha', 'perigo', 3, top=6)
    caution = states(table, 'amanha', 'atencao', 10, top=6)
    sentences['saude'] = ('E onde o tempo é mais perigoso para a saúde? Este mapa junta o calor e o ar seco. Em laranja, estão as áreas com trinta e oito graus ou mais, ou umidade abaixo de vinte por cento. '
                          'Em vermelho, quarenta graus ou mais, ou umidade abaixo de doze por cento. '
                          + (('O perigo maior amanhã está ' + joined(IN_STATE[n] for n, _ in danger) + '. ') if danger else
                             (('Amanhã, a maior atenção é ' + joined(IN_STATE[n] for n, _ in caution) + '. ') if caution else 'Amanhã, não há grandes áreas nessas faixas. '))
                          + 'Nas áreas de risco, beba água com frequência, mesmo sem sede. Evite o sol e os exercícios físicos no período mais quente do dia. '
                          'Fique atento a idosos, crianças e pessoas com doenças crônicas. E, se houver tontura, confusão ou mal-estar forte, procure atendimento médico.')
    region = ['Agora, região por região, a previsão de amanhã.']
    for macro, row in macros['amanha'].items():
        region.append(f'No {macro}, a máxima chega a {row["tmax"]:.0f} graus {IN_STATE[row["tmax_uf"]]}, a umidade pode cair a {row["rh"]} por cento {IN_STATE[row["rh_uf"]]}, '
                      f'e a chuva chega a {row["chuva"]} milímetros {IN_STATE[row["chuva_uf"]]}.')
    sentences['regioes'] = ' '.join(region)
    notes = []
    for name in ('Colômbia', 'Venezuela', 'Equador', 'Peru', 'Bolívia', 'Paraguai', 'Uruguai', 'Argentina', 'Chile', 'Guiana', 'Suriname'):
        row = table['pais:' + name]['amanha']
        facts = []
        if row['tmax'] >= 36:
            facts.append(f'máximas de até {row["tmax"]:.0f} graus')
        if row['tempestade'] >= 20:
            facts.append(f'tempestades em {row["tempestade"]} por cento do território')
        if row['chuva'] >= 40:
            facts.append(f'chuva de até {row["chuva"]} milímetros')
        if row['rh'] <= 15:
            facts.append(f'umidade perto de {row["rh"]} por cento')
        if facts:
            notes.append(f'{first_upper(IN_COUNTRY[name])}, a previsão para amanhã indica {joined(facts)}.')
    sentences['paises'] = ('Nos outros países da América do Sul, estes são os destaques. ' + ' '.join(notes[:8])
                           + ' São valores de modelo: confirme sempre com o serviço meteorológico de cada país.')
    sentences['fim'] = (f'Em resumo, para amanhã: o maior calor está no {hot_macro}, e as tempestades mais organizadas no {storm_macro}. Estes dados são previsões, e não são um aviso oficial. '
                        'Por isso, siga sempre a Defesa Civil e o Inmet. Vamos atualizar estas previsões todos os dias. '
                        'Inscreva-se no canal da Trovox Tempo e ative o sino para se manter informado. Até o próximo boletim!')
    return [[key, sentences[key]] for key in NUMBER_ORDER]


def youtube_text(table, today, tomorrow):
    hot = states(table, 'amanha', 'tmax', top=1)[0]
    dry = states(table, 'amanha', 'rh', top=1, reverse=False)[0]
    rain = states(table, 'amanha', 'chuva', top=1)[0]
    title = f'América do Sul: {hot[1]["tmax"]:.0f} °C {IN_STATE[hot[0]]}, ar seco e tempestades | {today:%d/%m} e {tomorrow:%d/%m}'
    description = (f'Boletim da Trovox Tempo com a previsão para {today:%d/%m/%Y} e {tomorrow:%d/%m/%Y} na América do Sul, com foco no Brasil: temperatura máxima, umidade mínima, '
                   'tempestades e os lugares mais perigosos para a saúde.\n\nDestaques para amanhã:\n'
                   f'- Calor: {hot[1]["tmax"]:.0f} °C {where(hot[0], hot[1], "tmax")}.\n- Ar seco: {dry[1]["rh"]}% de umidade {where(dry[0], dry[1], "rh")}.\n'
                   f'- Chuva: cerca de {rain[1]["chuva"]} mm {where(rain[0], rain[1], "chuva")}.\n\n'
                   'Risco de raios: modelo da Trovox. Chuva, temperatura e umidade: previsão do ECMWF (CC-BY 4.0). Valores de modelo, com cerca de 25 km de resolução: podem variar no local.\n'
                   'Faixas de umidade: referência usada em São Paulo pelo CGE e pela Defesa Civil. As faixas de calor são da Trovox.\n\n'
                   'Esta previsão não é um aviso oficial: siga a Defesa Civil e o Inmet. As orientações de saúde são gerais e não substituem atendimento médico.\n\n'
                   'Inscreva-se e ative o sino para se manter informado.\n\n'
                   'Apresentadora e voz geradas por IA. Satélite: GOES-19 (NOAA/NASA GIBS). Contornos: Natural Earth.\n#previsaodotempo #calor #tempestade #AmericaDoSul')
    return {'title': title[:100], 'description': description[:5000]}


def narrate(script, work):
    import edge_tts
    voices = work / 'voz'
    voices.mkdir(parents=True, exist_ok=True)

    async def speak():
        for name, text in script:
            await asyncio.wait_for(edge_tts.Communicate(text, 'pt-BR-FranciscaNeural', rate='-4%').save(str(voices / f'{name}.mp3')), timeout=120)
    asyncio.run(speak())
    timing, total = [], 0.0
    with open(voices / 'lista.txt', 'w') as listing:
        for name, _ in script:
            subprocess.run(['ffmpeg', '-y', '-v', 'error', '-i', str(voices / f'{name}.mp3'), '-af', 'apad=pad_dur=0.45', '-ar', '48000', '-ac', '2', str(voices / f'{name}.wav')], check=True)
            duration = float(subprocess.check_output(['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', str(voices / f'{name}.wav')]))
            timing.append([name, round(total, 3), round(duration, 3)])
            total += duration
            listing.write(f"file '{name}.wav'\n")
    subprocess.run(['ffmpeg', '-y', '-v', 'error', '-f', 'concat', '-safe', '0', '-i', str(voices / 'lista.txt'), '-c:a', 'pcm_s16le', str(work / 'narracao48.wav')], check=True)
    return timing, total


def fetch_clouds(now, folder, wanted=29, oldest_hours=7):
    """Recent ten-minute images. A blank answer means the layer has not reached that time yet."""
    folder.mkdir(parents=True, exist_ok=True)
    clock = now.astimezone(timezone.utc).replace(tzinfo=None, second=0, microsecond=0)
    clock -= timedelta(minutes=clock.minute % 10)
    times = [clock - timedelta(minutes=10 * k) for k in range(oldest_hours * 6)]

    def fetch(moment):
        path = folder / f'geo_{moment:%Y%m%dT%H%M}.jpg'
        if not path.exists():
            try:
                raw = get(GIBS.format(time=moment), timeout=150)
            except OSError:
                return None
            if len(raw) < 40_000:
                return None
            path.write_bytes(raw)
        return path
    with concurrent.futures.ThreadPoolExecutor(6) as pool:
        found = [p for p in pool.map(fetch, times) if p]
    found = sorted(found)[-wanted:]
    if len(found) < 12:
        raise RuntimeError('imagens de satélite insuficientes')
    return [str(p) for p in found]


# ---------------------------------------------------------------------- drawing
FB = '/usr/share/fonts/truetype/ubuntu/Ubuntu-B.ttf'
FR = '/usr/share/fonts/truetype/ubuntu/Ubuntu-R.ttf'
if not Path(FB).exists():
    FB, FR = '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf', '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'
INK, AMBER, TXT, MUT, OCEAN, LAND = (10, 16, 26), (255, 178, 56), (242, 244, 247), (178, 188, 200), (10, 18, 30), (31, 40, 52)
_fonts = {}


def font(path, size):
    return _fonts.setdefault((path, size), ImageFont.truetype(path, size))


def wrapped(draw, xy, value, path, size, colour=TXT, width=None, lead=1.22, shadow=False, anchor='la'):
    face, (x, y) = font(path, size), xy
    lines, current = [], ''
    if width:
        for word in value.split():
            attempt = (current + ' ' + word).strip()
            if draw.textlength(attempt, font=face) <= width:
                current = attempt
            else:
                lines.append(current)
                current = word
        lines.append(current)
    else:
        lines = [value]
    for line in lines:
        options = {'stroke_width': 3, 'stroke_fill': (5, 10, 18)} if shadow else {}
        draw.text((x, y), line, font=face, fill=colour, anchor=anchor, **options)
        y += int(size * lead)
    return y


def ease(x):
    x = min(1, max(0, x))
    return x * x * (3 - 2 * x)


def colour(hex_value):
    return tuple(int(hex_value[i:i + 2], 16) for i in (1, 3, 5))


RAIN_BANDS = [(1, '#000000', 0), (5, '#9ec5f4', .75), (15, '#6da7ec', .85), (30, '#3987e5', .92), (60, '#1c5cab', .96), (1e4, '#0d366b', 1)]
TEMP_BANDS = [(25, '#3a5068', .55), (30, '#7f8c5a', .8), (35, '#e3c054', .9), (38, '#ef8f3a', .95), (40, '#d9412d', 1), (1e4, '#7d0f24', 1)]
RH_BANDS = [(12, '#7d0f24', 1), (20, '#d9412d', 1), (30, '#ef8f3a', .95), (45, '#e3c054', .75), (65, '#7f9a78', .55), (1e4, '#3a5068', .5)]
LEGEND_STORM = [('#a24bd8', 'Raios e chuva juntos'), ('#3987e5', 'Chuva prevista (mais escuro: mais)')]
LEGEND_TEMP = [('#7d0f24', '40 °C ou mais'), ('#d9412d', '38 a 40 °C'), ('#ef8f3a', '35 a 38 °C'), ('#e3c054', '30 a 35 °C')]
LEGEND_RH = [('#7d0f24', 'Abaixo de 12%: emergência'), ('#d9412d', '12 a 20%: alerta'), ('#ef8f3a', '20 a 30%: atenção')]
LEGEND_HEALTH = [('#d0262c', '40 °C ou mais, ou umidade abaixo de 12%'), ('#ef8f3a', '38 °C ou mais, ou umidade abaixo de 20%')]


class MapMaker:
    """Forecast layers on one fixed South America window, at twice the screen size for the slow zooms."""
    LAT1, LAT0, LON_CENTRE = 10.0, -42.0, -58.0
    COS = math.cos(math.radians(16))

    def __init__(self, fields, outlines):
        import cv2
        self.cv2, self.fields = cv2, fields
        self.height, self.width = H * S2, MW * S2
        self.per_y = (self.LAT1 - self.LAT0) / self.height
        self.per_x = self.per_y / self.COS
        self.lon0 = self.LON_CENTRE - self.width / 2 * self.per_x
        land = Image.new('L', (self.width, self.height), 0)
        draw = ImageDraw.Draw(land)
        for country in outlines['paises']:
            if country['sul_americano']:
                for ring in country['aneis']:
                    draw.polygon([self.xy(y, x) for x, y in ring], fill=255)
        self.land = np.asarray(land, np.float32) / 255
        lines = Image.new('RGBA', (self.width, self.height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(lines)
        for state in outlines['estados']:
            for ring in state['aneis']:
                draw.line([self.xy(y, x) for x, y in ring], fill=(235, 240, 246, 95), width=2, joint='curve')
        for country in outlines['paises']:
            main = country['sul_americano']
            for ring in country['aneis']:
                draw.line([self.xy(y, x) for x, y in ring], fill=(245, 248, 252, 225 if main else 90), width=5 if main else 2, joint='curve')
        self.lines = np.asarray(lines, np.float32) / 255
        lon_index = (np.arange(self.width) * self.per_x + self.lon0 - fields['glon'][0]) / RES
        lat_index = (self.LAT1 - np.arange(self.height) * self.per_y - fields['glat'][0]) / -RES
        self.mx, self.my = np.meshgrid(lon_index.astype(np.float32), lat_index.astype(np.float32))

    def xy(self, lat, lon):
        return (lon - self.lon0) / self.per_x, (self.LAT1 - lat) / self.per_y

    def screen(self, field, method=None):
        cv2 = self.cv2
        return cv2.remap(np.nan_to_num(field.astype(np.float32), nan=0), self.mx, self.my, method or cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)

    def compose(self, fill, alpha):
        image = np.full((self.height, self.width, 3), OCEAN, np.float32)
        image = image * (1 - self.land[..., None]) + np.array(LAND, np.float32) * self.land[..., None]
        amount = (alpha * self.land)[..., None]
        return image * (1 - amount) + fill * amount

    def bands(self, value, stops):
        fill, alpha, low = np.zeros(value.shape + (3,), np.float32), np.zeros(value.shape, np.float32), -1e9
        for high, hex_value, opacity in stops:
            selected = (value >= low) & (value < high)
            fill[selected], alpha[selected] = colour(hex_value), opacity
            low = high
        return fill, alpha

    def storm(self, day):
        cv2 = self.cv2
        rain = cv2.GaussianBlur(self.screen(self.fields[day + '_rain']), (0, 0), 3)
        prob = cv2.GaussianBlur(self.screen(self.fields[day + '_prob'], cv2.INTER_LINEAR), (0, 0), 7)
        fill, alpha = self.bands(rain, RAIN_BANDS)
        both = (prob >= STORM_PROB) & (rain >= STORM_RAIN)
        fill[both], alpha[both] = colour('#a24bd8'), .92
        canvas = self.compose(fill, alpha).astype(np.uint8)
        contours, _ = cv2.findContours(((prob >= STORM_PROB) * self.land > .5).astype(np.uint8), cv2.RETR_LIST, cv2.CHAIN_APPROX_NONE)
        cv2.drawContours(canvas, [c for c in contours if len(c) > 60], -1, colour('#ff4d4d'), 5, cv2.LINE_AA)
        return canvas.astype(np.float32)

    def scalar(self, key, stops):
        fill, alpha = self.bands(self.cv2.GaussianBlur(self.screen(self.fields[key]), (0, 0), 2), stops)
        return self.compose(fill, alpha)

    def health(self, day):
        blur = lambda key: self.cv2.GaussianBlur(self.screen(self.fields[day + key]), (0, 0), 2)
        tmax, rh = blur('_tmax'), blur('_rh')
        fill, alpha = np.zeros(tmax.shape + (3,), np.float32), np.zeros(tmax.shape, np.float32)
        selected = (tmax >= HOT) | (rh < DRY_ALERT)
        fill[selected], alpha[selected] = colour('#ef8f3a'), .95
        selected = (tmax >= VERY_HOT) | (rh < DRY_EMERGENCY)
        fill[selected], alpha[selected] = colour('#d0262c'), 1
        return self.compose(fill, alpha)

    def with_labels(self, base, labels):
        """Lines on top, then value tags placed so that they never cover each other or leave the map."""
        cover = self.lines[..., 3:4]
        image = Image.fromarray(np.clip(base * (1 - cover) + self.lines[..., :3] * 255 * cover, 0, 255).astype(np.uint8))
        draw = ImageDraw.Draw(image, 'RGBA')
        boxes = []
        for name, value, lat, lon in labels:
            x, y = self.xy(lat, lon)
            big, small = font(FB, 42), font(FB, 36)
            width = max(draw.textlength(name, font=small), draw.textlength(value, font=big)) + 28
            for dx, dy in ((30, -50), (-30 - width, -50), (30, -160), (-30 - width, -160), (30, 60), (-30 - width, 60), (30, -270), (-30 - width, -270), (30, 170), (-30 - width, 170)):
                box = (x + dx, y + dy, x + dx + width, y + dy + 100)
                inside = box[0] > 10 and box[1] > 10 and box[2] < self.width - 10 and box[3] < self.height - 10
                if inside and not any(box[0] < b[2] + 8 and box[2] > b[0] - 8 and box[1] < b[3] + 8 and box[3] > b[1] - 8 for b in boxes):
                    break
            boxes.append(box)
            draw.line((x, y, box[0] if dx > 0 else box[2], box[1] + 50), fill=(255, 255, 255, 220), width=3)
            draw.ellipse((x - 11, y - 11, x + 11, y + 11), fill=(255, 255, 255, 255), outline=(5, 10, 18, 255), width=4)
            draw.rounded_rectangle(box, 12, fill=(6, 12, 22, 225))
            draw.text((box[0] + 14, box[1] + 6), value, font=big, fill=AMBER)
            draw.text((box[0] + 14, box[1] + 52), name, font=small, fill=TXT)
        return np.asarray(image)

    def camera(self, zoom, lat, lon):
        x, y = self.xy(lat, lon)
        scale = zoom / S2
        tx = min(0, max(MW - scale * self.width, MW / 2 - scale * x))
        ty = min(0, max(H - scale * self.height, H / 2 - scale * y))
        return np.array([[scale, 0, tx], [0, scale, ty]], np.float32)


def panel(title, day, bullets, legend=None, source=None):
    image = Image.new('RGB', (W - MW, H), INK)
    draw = ImageDraw.Draw(image)
    x, width = 44, W - MW - 88
    draw.rectangle((0, 0, 6, H), fill=AMBER)
    wrapped(draw, (x, 34), 'TROVOX TEMPO', FB, 26, AMBER)
    y = wrapped(draw, (x, 72), title, FB, 50, TXT, width, 1.08)
    if day:
        y = wrapped(draw, (x, y + 4), day, FR, 30, AMBER, width)
    y += 18
    for hex_value, label in legend or []:
        draw.rounded_rectangle((x, y, x + 34, y + 30), 6, fill=colour(hex_value))
        y = wrapped(draw, (x + 46, y + 1), label, FR, 26, TXT, width - 46) + 10
    y += 8
    for bullet in bullets:
        draw.ellipse((x, y + 11, x + 12, y + 23), fill=AMBER)
        y = wrapped(draw, (x + 26, y), bullet, FR, 29, TXT, width - 26, 1.2) + 10
    wrapped(draw, (x, 1036), source or 'Previsão do modelo da Trovox e ECMWF. Não é aviso oficial.', FR, 21, MUT, width)
    return np.asarray(image)


def label_rows(rows, value_key, field, formatter):
    labels = []
    for name, row in rows:
        place = row[field + '_em']
        labels.append((f'{place}, {UF[name]}' if place else name, formatter(row[value_key]), row[field + '_lat'], row[field + '_lon']))
    return labels


def build_scenes(maker, table, today, tomorrow):
    pct = lambda v: f'{v}%'
    degrees = lambda v: f'{v:.0f} °C'
    mm = lambda v: f'{v} mm'
    def centre(rows, field):
        return (float(np.mean([r[field + '_lat'] for _, r in rows])), float(np.mean([r[field + '_lon'] for _, r in rows])))
    layers, scenes = {}, {}
    today_tag, tomorrow_tag = f'HOJE, {today:%d/%m}', f'AMANHÃ, {tomorrow:%d/%m}'
    for key, tag in (('hoje', today_tag), ('amanha', tomorrow_tag)):
        rain = states(table, key, 'chuva', top=3)
        layers[key] = maker.with_labels(maker.storm(key), label_rows(rain, 'chuva', 'chuva', mm))
        best = states(table, key, 'tempestade', 5, top=2)
        lat, lon = centre(rain, 'chuva')
        scenes[key] = dict(layer=key, zoom=(1.0, 1.5), at=(lat, lon), panel=panel('Tempestades', tag, ['Linha vermelha: risco alto de raios']
                           + [f'{name}: {row["tempestade"]}% com raios e chuva juntos' for name, row in best] + [f'Chuva: até {rain[0][1]["chuva"]} mm'], LEGEND_STORM))
    for prefix, key, stops, value, field, fmt, title, legend, source in (('t', 'tmax', TEMP_BANDS, 'tmax', 'tmax', degrees, 'Temperatura máxima', LEGEND_TEMP, None),
                                                                        ('h', 'rh', RH_BANDS, 'rh', 'rh', pct, 'Umidade mínima', LEGEND_RH, 'Faixas de umidade: referência do CGE e da Defesa Civil em SP. Previsão ECMWF.')):
        reverse = key == 'tmax'
        rows = {}
        for index, day in enumerate(('hoje', 'amanha')):
            rows[day] = states(table, day, value, top=3, reverse=reverse)
            layers[f'{prefix}{index}'] = maker.with_labels(maker.scalar(f'{day}_{key}', stops), label_rows(rows[day], value, field, fmt))
        lat, lon = centre(rows['amanha'], field)
        bullets = [f'{name}: {fmt(row[value])} amanhã' for name, row in rows['amanha']]
        scenes['calor' if key == 'tmax' else 'umidade'] = dict(layer=f'{prefix}0', then=f'{prefix}1', tags=(today_tag, tomorrow_tag), zoom=(1.2, 1.6), at=(lat, lon),
                                                               panel=panel(title, f'{today_tag}, DEPOIS {tomorrow_tag}', bullets, legend, source))
    danger = states(table, 'amanha', 'atencao', top=5)
    layers['s0'], layers['s1'] = maker.with_labels(maker.health('hoje'), []), maker.with_labels(maker.health('amanha'), [])
    scenes['saude'] = dict(layer='s0', then='s1', tags=(today_tag, tomorrow_tag), zoom=(1.0, 1.3), at=(float(np.mean([r['rh_lat'] for _, r in danger])), float(np.mean([r['rh_lon'] for _, r in danger]))),
                           panel=panel('Perigo para a saúde', f'{today_tag}, DEPOIS {tomorrow_tag}', ['Beba água, mesmo sem sede', 'Evite sol e exercício nas horas mais quentes', 'Atenção a idosos, crianças e doentes crônicos'], LEGEND_HEALTH,
                                       'Orientação geral. Em caso de mal-estar, procure atendimento médico.'))
    macros = macro_row(table, 'amanha')
    scenes['regioes'] = dict(layer='amanha', zoom=(1.0, 1.1), at=(-14.0, -52.0), panel=panel('Região por região', tomorrow_tag,
                             [f'{m}: até {r["tmax"]:.0f} °C, {r["rh"]}%, {r["chuva"]} mm' for m, r in macros.items()], source='Máxima, umidade mínima e maior chuva previstas.'))
    scenes['paises'] = dict(layer='amanha', zoom=(1.0, 1.1), at=(-14.0, -62.0), panel=panel('América do Sul', tomorrow_tag, ['Destaques por país na narração', 'Mais roxo: raios e chuva juntos'], LEGEND_STORM, 'Valores do modelo; confirme com o serviço meteorológico local.'))
    return layers, scenes


class Clouds:
    SP, LAT1, LON0 = 66 / 2112, 16.0, -90.0

    def __init__(self, files):
        import cv2
        self.cv2, self.files, self.images, self.flows = cv2, files, {}, {}
        first = cv2.imread(files[0])
        self.h, self.w = first.shape[:2]
        self.flow_engine = cv2.DISOpticalFlow_create(cv2.DISOPTICAL_FLOW_PRESET_FAST)
        self.gx, self.gy = np.meshgrid(np.arange(self.w, dtype=np.float32), np.arange(self.h, dtype=np.float32))

    def image(self, i):
        if i not in self.images:
            if len(self.images) > 5:
                self.images.pop(next(iter(self.images)))
            self.images[i] = self.cv2.cvtColor(self.cv2.imread(self.files[i]), self.cv2.COLOR_BGR2RGB)
        return self.images[i]

    def flow(self, i):
        if i not in self.flows:
            if len(self.flows) > 2:
                self.flows.pop(next(iter(self.flows)))
            cv2 = self.cv2
            a, b = [cv2.resize(cv2.cvtColor(self.image(k), cv2.COLOR_RGB2GRAY), (self.w // 2, self.h // 2), interpolation=cv2.INTER_AREA) for k in (i, i + 1)]
            self.flows[i] = (cv2.resize(self.flow_engine.calc(a, b, None), (self.w, self.h)) * 2, cv2.resize(self.flow_engine.calc(b, a, None), (self.w, self.h)) * 2)
        return self.flows[i]

    def frame(self, progress, height, lat, lon):
        cv2 = self.cv2
        q = min(max(progress, 0), 1) * (len(self.files) - 1.001)
        i, part = int(q), q - int(q)
        forward, backward = self.flow(i)
        one = cv2.remap(self.image(i), self.gx - part * forward[..., 0], self.gy - part * forward[..., 1], cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
        two = cv2.remap(self.image(i + 1), self.gx - (1 - part) * backward[..., 0], self.gy - (1 - part) * backward[..., 1], cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
        mixed = cv2.addWeighted(one, 1 - part, two, part, 0)
        scale = H / height
        sx = scale * math.cos(math.radians(16))
        x, y = (lon - self.LON0) / self.SP, (self.LAT1 - lat) / self.SP
        view = cv2.warpAffine(mixed, np.array([[sx, 0, W / 2 - sx * x], [0, scale, H / 2 - scale * y]], np.float32), (W, H), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
        return np.clip(view.astype(np.float32) * 1.08, 0, 255).astype(np.uint8), q


def overlay(paint):
    image = Image.new('RGBA', (W, H), (0, 0, 0, 0))
    paint(ImageDraw.Draw(image))
    array = np.asarray(image, np.float32)
    return array[..., :3], array[..., 3:4] / 255


def blend(frame, layer, amount=1.0):
    return (frame * (1 - layer[1] * amount) + layer[0] * layer[1] * amount).astype(np.uint8)


def render_video(path, timing, layers, scenes, maker, clouds, cloud_times, table, today, tomorrow):
    cv2 = maker.cv2
    SC = {name: (start, length) for name, start, length in timing}
    total = sum(length for _, _, length in timing)
    shade = np.zeros((H, W, 4), np.float32)
    shade[..., :3] = INK
    shade[700:, :, 3] = np.linspace(0, 235, 380)[:, None]
    shade[:190, :, 3] = np.linspace(190, 0, 190)[:, None]
    shade = (shade[..., :3], shade[..., 3:4] / 255)

    def chip(draw, index, label, fill, ink):
        draw.rounded_rectangle((60 + index * 290, 955, 334 + index * 290, 1012), 28, fill=fill)
        wrapped(draw, (197 + index * 290, 967), label, FB, 28, ink, anchor='ma')
    def opening(draw):
        wrapped(draw, (60, 40), 'TROVOX TEMPO', FB, 34, AMBER)
        wrapped(draw, (60, 800), 'Boletim da América do Sul', FB, 72, TXT)
        wrapped(draw, (60, 892), f'Previsão para hoje, {today:%d/%m}, e amanhã, {tomorrow:%d/%m}. Foco no Brasil.', FR, 36, TXT)
        chip(draw, 0, 'CALOR', (217, 65, 45), (255, 255, 255))
        chip(draw, 1, 'UMIDADE', (239, 143, 58), INK)
        chip(draw, 2, 'TEMPESTADES', (162, 75, 216), (255, 255, 255))
    macros = macro_row(table, 'amanha')
    hot_macro = max(macros, key=lambda m: macros[m]['acima38'])
    storm_macro = max(macros, key=lambda m: macros[m]['tempestade'])
    open_layer = overlay(opening)
    overview = overlay(lambda d: (wrapped(d, (60, 40), 'TROVOX TEMPO', FB, 34, AMBER), wrapped(d, (60, 860), 'Amanhã no Brasil', FB, 66, TXT),
                                  wrapped(d, (60, 948), f'Maior calor: {hot_macro}. Tempestades mais organizadas: {storm_macro}.', FR, 34, TXT)))
    def ending(draw):
        draw.rectangle((0, 0, W, H), fill=INK + (205,))
        wrapped(draw, (110, 110), 'TROVOX TEMPO', FB, 36, AMBER)
        wrapped(draw, (110, 170), 'Em resumo, amanhã', FB, 72, TXT)
        for i, (hue, value) in enumerate((((217, 65, 45), f'Maior calor: {hot_macro}'), ((162, 75, 216), f'Tempestades mais organizadas: {storm_macro}'), (AMBER, 'Atualizamos estas previsões todos os dias'))):
            draw.ellipse((110, 306 + i * 92, 134, 330 + i * 92), fill=hue)
            wrapped(draw, (154, 296 + i * 92), value, FR, 40, TXT, 1040)
        draw.rounded_rectangle((110, 640, 720, 760), 60, fill=(214, 48, 49))
        wrapped(draw, (415, 668), 'INSCREVA-SE', FB, 58, (255, 255, 255), anchor='ma')
        wrapped(draw, (110, 800), 'Ative o sino para se manter informado.', FB, 38, AMBER)
        wrapped(draw, (110, 980), 'Previsões, não aviso oficial: siga a Defesa Civil e o Inmet.', FR, 26, MUT)
    end_layer = overlay(ending)
    credit = overlay(lambda d: wrapped(d, (W - 60, 44), 'Imagens reais do satélite GOES-19', FR, 26, TXT, anchor='ra', shadow=True))

    def with_clock(frame, q):
        i = int(q)
        moment = cloud_times[i] + (cloud_times[min(i + 1, len(cloud_times) - 1)] - cloud_times[i]) * (q - i)
        image = Image.fromarray(frame)
        wrapped(ImageDraw.Draw(image), (W - 60, 82), moment.astimezone(BRT).strftime('%H:%M'), FB, 54, TXT, shadow=True, anchor='ra')
        return np.asarray(image)

    def render(t):
        name = next((k for k, (a, d) in SC.items() if a <= t < a + d), 'fim')
        start, length = SC[name]
        u = (t - start) / length
        if name == 'abertura':
            frame, q = clouds.frame(u, 1100 - 160 * ease(u), -15, -57)
            return blend(with_clock(blend(blend(frame, shade), open_layer, ease(t / 1.2)), q), credit)
        if name == 'panorama':
            frame, q = clouds.frame(u, 900 - 120 * ease(u), -15, -52)
            return blend(with_clock(blend(blend(frame, shade), overview, ease((t - start) / 1.0)), q), credit)
        if name == 'fim':
            frame, _ = clouds.frame(u, 1050, -18, -57)
            return blend(frame, end_layer, ease((t - start) / 1.0))
        scene = scenes[name]
        low, high = scene['zoom']
        matrix = maker.camera(low + (high - low) * ease(u), *scene['at'])
        base = layers[scene['layer']]
        if 'then' in scene:
            k = ease((u - .48) / .06)
            base = base if k == 0 else layers[scene['then']] if k == 1 else (base * (1 - k) + layers[scene['then']] * k).astype(np.uint8)
        frame = np.full((H, W, 3), INK, np.uint8)
        frame[:, :MW] = cv2.warpAffine(base, matrix, (MW, H), flags=cv2.INTER_LINEAR)
        frame[:, MW:] = scene['panel']
        if 'tags' in scene:
            tag = scene['tags'][u >= .5]
            image = Image.fromarray(frame)
            draw = ImageDraw.Draw(image)
            width = draw.textlength(tag, font=font(FB, 40)) + 44
            draw.rounded_rectangle((30, 30, 30 + width, 94), 12, fill=AMBER)
            draw.text((52, 40), tag, font=font(FB, 40), fill=INK)
            frame = np.asarray(image)
        return frame
    cuts = [SC[k][0] for k in NUMBER_ORDER[1:]]
    encoder = subprocess.Popen(['ffmpeg', '-y', '-v', 'error', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-s', f'{W}x{H}', '-r', str(FPS), '-i', '-',
                                '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '20', '-pix_fmt', 'yuv420p', str(path)], stdin=subprocess.PIPE)
    try:
        frames = int(total * FPS)
        for i in range(frames):
            t = i / FPS
            frame = render(t)
            gap = min([abs(t - c) for c in cuts] + [t, total - t])
            if gap < .25:
                frame = (frame * (gap / .25) + np.array(INK) * (1 - gap / .25)).astype(np.uint8)
            encoder.stdin.write(frame.tobytes())
            if i % 2000 == 0:
                print(f'quadro {i}/{frames}', flush=True)
    finally:
        encoder.stdin.close()
        encoder.wait(timeout=300)
    if encoder.returncode:
        raise RuntimeError('falha ao codificar o boletim')
    return total


def produce(directory, now=None, publish_at=None):
    """Compose boletim.mp4 and its YouTube text in `directory`."""
    from .shorts_presenter import synchronize
    directory = Path(directory).resolve()
    work = directory / 'dados'
    work.mkdir(parents=True, exist_ok=True)
    now = now or datetime.now(timezone.utc)
    fields = load_fields(now, max(now, publish_at) if publish_at else now, work)
    outlines = json.loads((ASSETS / 'contornos.json').read_text())
    table = regional_table(fields, outlines, load_places())
    today, tomorrow = [datetime.fromisoformat(d).date() for d in fields['days']]
    (directory / 'destaques.json').write_text(json.dumps(table, ensure_ascii=False, indent=1))
    script = write_narration(table, today, tomorrow)
    (directory / 'roteiro.json').write_text(json.dumps(script, ensure_ascii=False, indent=1))
    (directory / 'youtube-metadata.json').write_text(json.dumps(youtube_text(table, today, tomorrow), ensure_ascii=False, indent=1))
    timing, total = narrate(script, work)
    (directory / 'tempos.json').write_text(json.dumps(timing))
    print(f'Narração: {total:.0f} s; rodada ECMWF {fields["run"]:%d/%m %H} UTC', flush=True)
    files = fetch_clouds(now, work / 'nuvens')
    cloud_times = [datetime.strptime(Path(f).stem[4:], '%Y%m%dT%H%M').replace(tzinfo=timezone.utc) for f in files]
    maker = MapMaker(fields, outlines)
    layers, scenes = build_scenes(maker, table, today, tomorrow)
    base = directory / 'base.mp4'
    render_video(base, timing, layers, scenes, maker, Clouds(files), cloud_times, table, today, tomorrow)
    subprocess.run(['ffmpeg', '-y', '-v', 'error', '-i', str(work / 'narracao48.wav'), '-c:a', 'libmp3lame', '-b:a', '160k', str(directory / 'voz.mp3')], check=True)
    print('Sincronizando apresentadora...', flush=True)
    presenter = synchronize(directory, timeout=5400)
    music = ROOT / 'templates/fundo-musical.wav'
    fade = max(total - 3, 0)
    subprocess.run(['ffmpeg', '-y', '-v', 'error', '-i', str(base), '-i', str(presenter), '-i', str(work / 'narracao48.wav'), '-stream_loop', '-1', '-i', str(music), '-filter_complex',
                    f'[1:v]fps={FPS},setpts=PTS-STARTPTS,crop=iw:min(ih\\,iw*1.09):0:0,scale=340:-2,pad=iw+8:ih+8:4:4:color=0xFFB238[p];[0:v][p]overlay=1536:640:shortest=0[v];'
                    f'[3:a]volume=0.07,afade=t=out:st={fade:.1f}:d=2.8[m];[2:a][m]amix=inputs=2:duration=first:normalize=0,alimiter=limit=0.95[a]',
                    '-map', '[v]', '-map', '[a]', '-t', f'{total:.3f}', '-c:v', 'libx264', '-preset', 'medium', '-crf', '20', '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-b:a', '192k',
                    '-movflags', '+faststart', str(directory / 'boletim.mp4')], check=True, timeout=3600)
    shutil.rmtree(work / 'nuvens', ignore_errors=True)
    for leftover in glob.glob(str(work / '*.grib2')):
        Path(leftover).unlink(missing_ok=True)
    return directory / 'boletim.mp4'
