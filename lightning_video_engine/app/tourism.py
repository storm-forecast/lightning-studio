"""Tourist cities are an editorial watchlist, not evidence of weather risk."""
import json
import unicodedata
from pathlib import Path


def _key(value):
    return ''.join(c for c in unicodedata.normalize('NFD', str(value).casefold())
                   if unicodedata.category(c) != 'Mn').strip()


def tourism_evidence(scene):
    if not scene.available:
        return []
    watchlist = json.loads((Path(__file__).resolve().parents[2] / 'templates/cidades-turisticas.json').read_text())
    targets = {_key(x['cidade']): x for x in watchlist}
    editorial = scene.evidence.get('editorial', {})
    if scene.view == 'chuva-prevista':
        rows = editorial.get('chuva', {}).get('regioes', [])
    elif scene.category in ('previsao', 'destaque'):
        rows = editorial.get('brasil_maior_atividade_raios', []) + editorial.get('raios', {}).get('regioes', [])
        if scene.place:
            name = _key(scene.place.get('nome', '').split(',')[0])
            rows = [x for x in rows if _key(x.get('cidade', '')) == name]
    elif scene.id in ('05-agora', '07-alagamento'):
        rows = scene.evidence.get('flood_references', {}).get('locais_interesse', [])
        rows = [x for x in rows if x.get('dentro_poligono') is True]
    elif scene.id == '06-observado':
        rows = scene.evidence.get('observed', {}).get('regioes', [])
    else:
        # Polygon counts without georeferenced city associations cannot locate tourism risks.
        return []
    selected, seen = [], set()
    for row in rows:
        name = _key(row.get('cidade', ''))
        target = targets.get(name)
        if not target or _key(row.get('pais', '')) not in ('brasil', 'brazil') or name in seen:
            continue
        uf = row.get('uf')
        if uf and _key(uf) != _key(target['uf']):
            continue
        # Bonito has namesakes in other states. Do not infer the MS destination.
        if name == 'bonito' and _key(uf or '') != 'ms' and _key(row.get('estado','')) != 'mato grosso do sul':
            continue
        if scene.id == '06-observado' and not (isinstance(row.get('raios'), (int, float)) and row['raios'] > 0):
            continue
        seen.add(name)
        selected.append(dict(row))
    return selected[:3]


def tourism_direction(scene):
    matches = tourism_evidence(scene)
    if not matches:
        return ''
    names = ', '.join(x['cidade'] for x in matches)
    return (f'Entre os dados deste produto há lugares da lista de atenção turística: {names}. '
            'Mencione-os brevemente se houver destaque meteorológico relevante para o período '
            'exibido; não acrescente fatos turísticos à narração. Use apenas lugares de destaque, '
            'sem chamar de maior risco nem alterar a prioridade das áreas com fenômenos mais relevantes. '
            'Não transforme observação em previsão, risco em ocorrência ou a lista em alerta.')


STATE_NAMES = {'RJ':'Rio de Janeiro','SP':'São Paulo','BA':'Bahia','SC':'Santa Catarina',
               'PR':'Paraná','CE':'Ceará','RN':'Rio Grande do Norte','PE':'Pernambuco',
               'RS':'Rio Grande do Sul','MG':'Minas Gerais','AM':'Amazonas','PA':'Pará',
               'MS':'Mato Grosso do Sul','DF':'Distrito Federal'}


def tourism_targets():
    path = Path(__file__).resolve().parents[2] / 'templates/cidades-turisticas.json'
    return [{'cidade':x['cidade'], 'estado':STATE_NAMES[x['uf']]} for x in json.loads(path.read_text())]


def observed_tourism_copy(scene):
    if scene.id != '06-observado':
        return ''
    matches = tourism_evidence(scene)
    if not matches:
        return ''
    return ('Entre os lugares de destaque com raios observados estão ' +
            '; '.join(f"a região de {x['cidade']}, com {x['raios']} descargas" for x in matches) +
            '. As contagens são de áreas próximas, não de todo o município.')
