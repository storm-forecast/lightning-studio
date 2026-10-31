"""Concrete Brazilian places and spoken time references for each product."""
from datetime import datetime, timezone, timedelta
import re


def brazilian_highlights(scene):
    editorial = scene.evidence.get('editorial', {})
    if scene.id == '01-chuva':
        rows = editorial.get('chuva', {}).get('regioes', [])
    elif scene.id == '02-ecens':
        rows = editorial.get('brasil_maior_atividade_raios', [])
    elif scene.id == '06-observado':
        rows = scene.evidence.get('observed', {}).get('regioes', [])
    else:
        return []
    names = []
    for row in rows:
        if str(row.get('pais', '')).casefold() in ('brasil', 'brazil') and row.get('cidade'):
            name = row['cidade'].strip()
            if name not in names:
                names.append(name)
    return names[:3]


def spoken_utc(value):
    try:
        date = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if date.utcoffset() is not None and date.utcoffset().total_seconds() != 0:
            from datetime import timezone
            date = date.astimezone(timezone.utc)
        return date.strftime('%d/%m/%Y às %H:%M UTC')
    except (ValueError, TypeError, AttributeError):
        return None


def time_reference(scene):
    if not scene.available:
        return ''
    if scene.category in ('previsao', 'destaque'):
        window = scene.metadata.get('forecast_window') or {}
        start, end = spoken_utc(window.get('inicio')), spoken_utc(window.get('fim'))
        if start and end:
            return f'Validade desta previsão: de {start} até {end}.'
        period = str(scene.metadata.get('period', '')).strip()
        if period and period.casefold() not in ('consulte a validade na legenda', 'não informado', 'none'):
            return f'Validade desta previsão: {period.rstrip(".")}.'
        return 'A validade desta previsão não pôde ser confirmada nesta consulta.'
    if scene.id == '06-observado':
        observed = scene.evidence.get('observed', {})
        start, end = spoken_utc(observed.get('inicio')), spoken_utc(observed.get('fim'))
        if start and end:
            return f'As observações abrangem de {start} até {end}.'
        return 'O período das observações não pôde ser confirmado nesta consulta.'
    if scene.category in ('nowcasting', 'alagamento', 'extrapolacao'):
        now = scene.metadata.get('nowcast') or {}
        stamps = []
        for key, label in (('raios_ate', 'Raios observados até'), ('nuvens_de', 'Imagem de nuvens de')):
            stamp = spoken_utc(now.get(key))
            if stamp:
                stamps.append(f'{label} {stamp}.')
        return ' '.join(stamps) or 'A referência temporal do monitoramento não pôde ser confirmada nesta consulta.'
    return ''


def add_time_reference(scene, spoken_periods=None):
    reference = time_reference(scene)
    if not reference:
        return
    # Remove our own suffix from resumed scripts before applying bulletin-wide rules.
    normalized = readable_times(reference)
    scene.narration = scene.narration.replace(reference, '').replace(normalized, '').strip()
    if scene.category in ('previsao', 'destaque') and spoken_periods is not None:
        if normalized in spoken_periods:
            return
        spoken_periods.add(normalized)
    scene.narration = scene.narration.rstrip() + ' ' + reference


def local_recommendations(segments):
    names = []
    for scene in segments:
        if scene.available and scene.category == 'destaque' and scene.place and scene.place.get('nome'):
            if scene.place['nome'] not in names:
                names.append(scene.place['nome'])
    if not names:
        return ''
    return ('Nas áreas destacadas na previsão de raios, como ' + '; '.join(names[:2]) +
            ', se houver tempestade, procure abrigo em uma construção fechada e evite árvores, '
            'áreas abertas, praias e piscinas. Não atravesse vias alagadas e acompanhe os avisos da Defesa Civil.')


_ISO_TIMESTAMP = re.compile(r'\b\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:\d{2})\b')


def readable_times(text, include_brasilia=False):
    """Normalize presentation copy only; retain raw timestamps in evidence."""
    text = _ISO_TIMESTAMP.sub(lambda m: spoken_utc(m.group()) or m.group(), str(text))
    text = re.sub(r'\b(\d{1,2}:\d{2}(?::\d{2})?)\s*Z\b', r'\1 UTC', text)
    text = re.sub(r'\bUTC(?:\s+UTC)+\b', 'UTC', text)
    if include_brasilia:
        from zoneinfo import ZoneInfo
        def full_time(match):
            date = datetime.strptime(match.group(1), '%d/%m/%Y às %H:%M').replace(tzinfo=timezone.utc)
            local = date.astimezone(ZoneInfo('America/Sao_Paulo'))
            return match.group() + local.strftime(' (%H:%M de %d/%m/%Y, horário de Brasília)')
        text = re.sub(r'(\d{2}/\d{2}/\d{4} às \d{2}:\d{2}) UTC(?! \()', full_time, text)
        def clock(match):
            hour, minute = int(match.group(1)), int(match.group(2))
            if hour > 23 or minute > 59:
                return match.group()
            minutes = hour * 60 + minute - 180
            local = minutes % 1440
            day = ', do dia anterior' if minutes < 0 else ''
            return match.group() + f' ({local // 60:02d}:{local % 60:02d} no horário de Brasília{day})'
        text = re.sub(r'\b(\d{1,2}):(\d{2}) UTC(?! \()', clock, text)
    return text
