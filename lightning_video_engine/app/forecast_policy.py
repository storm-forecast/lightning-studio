"""Forecast attribution contract: ECENS only; lightning is an AI-derived product."""
import re

# Editorial name used on screen and in narration. The final acronym preserves
# the exact technical source identifier validated below.
ECENS_EDITORIAL_NAME = 'modelo do Centro Europeu de Previsões Meteorológicas a Médio Prazo (ECMWF), o ECENS'
LIGHTNING_METHOD = 'Previsão de Raios'


def validate_forecasts(segments):
    for scene in segments:
        if scene.category not in ('previsao', 'destaque'):
            continue
        if scene.source != 'ecens':
            raise ValueError(f'{scene.id}: previsões devem usar exclusivamente ECENS; recapture a cena')
        if scene.available and scene.metadata.get('source') != 'ecens':
            raise ValueError(f'{scene.id}: captura não confirma fonte ECENS')


def validate_forecast_text(scene):
    if scene.category not in ('previsao', 'destaque') or not scene.available:
        return
    if 'gfs' in scene.narration.casefold():
        raise ValueError(f'{scene.id}: narração antiga com fonte GFS; gere o áudio novamente')
    validate_narration_layer(scene)
    if scene.view in ('deterministico', 'probabilidade', 'risco'):
        words = scene.narration.casefold()
        if re.search(r'ecens|ecmwf|inteligência artificial|\bia\b|convectiv|parâmetros', words):
            raise ValueError(f'{scene.id}: use apenas Previsão de Raios na narração, sem explicar o método')
        if re.search(r'\bchuvas?\b|precipita|pluviom|milímetros|\bmm\b', words):
            raise ValueError(f'{scene.id}: fala de chuva em uma cena de previsão de raios')


def narration_view(scene):
    """Choose the lightning metric actually discussed; never mix metrics silently."""
    if scene.category not in ('previsao','destaque') or scene.view not in ('deterministico','probabilidade','risco'):
        return scene.view
    text=scene.narration.casefold()
    probability=bool(re.search(r'probabilidades?|percentua(?:l|is)|por\s+cento|%|\bchances?\b',text))
    counts=bool(re.search(r'(?:número|quantidade|contagem)\s+(?:previst[oa]\s+)?(?:de\s+)?(?:raios|descargas)|acumulad[oa]s?\s+(?:previst[oa]s?\s+)?(?:de\s+)?(?:raios|descargas)|\d[\d., ]*\s+(?:raios|descargas)',text))
    # A count may be written without the unit repeated, or spoken in words.
    counts = counts or bool(re.search(r'\bacumulad[oa]s?\b|\b(?:cem|cento|duzentos|trezentos|quinhentos|mil|milhões)\s+(?:e\s+)?(?:raios|descargas)\b',text))
    if probability and counts:
        raise ValueError(f'{scene.id}: divida probabilidade (%) e quantidade de raios em cenas separadas')
    if probability:return 'probabilidade'
    if counts:return 'deterministico'
    return scene.view


def validate_narration_layer(scene):
    if not scene.available:return
    expected=narration_view(scene)
    if scene.view!=expected:
        raise ValueError(f'{scene.id}: a fala exige camada {expected}, não {scene.view}')
    if scene.metadata.get('view') and scene.metadata['view']!=scene.view:
        raise ValueError(f'{scene.id}: imagem carregada não corresponde à camada declarada')
