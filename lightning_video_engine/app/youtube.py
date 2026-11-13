"""YouTube Data API v3 upload with a stored OAuth refresh token (standard library only)."""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

TOKEN_URL = 'https://oauth2.googleapis.com/token'
AUTH_URL = 'https://accounts.google.com/o/oauth2/v2/auth'
API = 'https://www.googleapis.com/youtube/v3'
UPLOAD = 'https://www.googleapis.com/upload/youtube/v3/videos'
# upload publishes; readonly lets us confirm which channel the token belongs to.
SCOPES = ('https://www.googleapis.com/auth/youtube.upload',
          'https://www.googleapis.com/auth/youtube.readonly')
PRIVACY = {'private', 'unlisted', 'public'}
NEWS_CATEGORY = '25'
TAGS = ['previsão do tempo', 'boletim meteorológico', 'raios', 'chuva', 'tempo severo',
        'Brasil', 'América do Sul', 'ECENS', 'nowcasting', 'Lightning Agent']


class YouTubeError(RuntimeError):
    pass


class QuotaExceeded(YouTubeError):
    """Daily API quota or channel upload limit reached; the next slot may succeed."""


QUOTA_FILE = 'quota.json'


def block_quota(root: Path, reason: str, now=None):
    """Record the latest YouTube limit for diagnosis without pausing the monitors.

    The limit is never trusted to last: the next pass simply tries again, so a
    transient rate or channel limit cannot silence the Shorts for a whole day.
    """
    now = now or datetime.now(timezone.utc)
    (Path(root) / QUOTA_FILE).write_text(json.dumps({'ultimo_limite': now.isoformat(), 'motivo': reason}, ensure_ascii=False))
    return now


def _request(url, *, data=None, headers=None, method=None):
    request = urllib.request.Request(url, data=data, headers=headers or {}, method=method)
    try:
        with urllib.request.urlopen(request, timeout=600) as response:
            body = response.read()
            return response.headers, json.loads(body) if body else {}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors='replace')
        try:
            reasons = {e.get('reason') for e in json.loads(detail)['error'].get('errors', [])}
        except (ValueError, KeyError, AttributeError):
            reasons = set()
        if reasons & {'quotaExceeded', 'uploadLimitExceeded', 'rateLimitExceeded'}:
            raise QuotaExceeded(f'limite do YouTube atingido: {", ".join(sorted(reasons))}') from exc
        raise YouTubeError(f'HTTP {exc.code} em {url.split("?")[0]}: {detail[:500]}') from exc


def exchange_token(client_id, client_secret, **fields):
    """Exchange an authorization code or refresh token at Google's token endpoint."""
    data = urllib.parse.urlencode({'client_id': client_id, 'client_secret': client_secret, **fields}).encode()
    return _request(TOKEN_URL, data=data, headers={'Content-Type': 'application/x-www-form-urlencoded'})[1]


def access_token(client_id, client_secret, refresh_token):
    return exchange_token(client_id, client_secret, refresh_token=refresh_token,
                          grant_type='refresh_token')['access_token']


def authorized_channel(token):
    items = _request(f'{API}/channels?part=id,snippet&mine=true',
                     headers={'Authorization': f'Bearer {token}'})[1].get('items', [])
    if not items:
        raise YouTubeError('a conta autorizada não possui canal no YouTube')
    return items[0]['id'], items[0]['snippet'].get('title', '')


def bulletin_metadata(directory: Path, presented_at: datetime, *, timezone_name='America/Belem', privacy='private', publish_at=None):
    if privacy not in PRIVACY:
        raise ValueError(f'YOUTUBE_PRIVACY deve ser um de {sorted(PRIVACY)}')
    local = presented_at.astimezone(ZoneInfo(timezone_name))
    when = f'{local:%d/%m/%Y} às {local:%H}h'
    title = f'Boletim do tempo | Raios, chuva e tempo severo no Brasil — {when}'
    highlights = []
    editorial = directory / 'destaques-ecens.json'
    if editorial.is_file():
        rows = json.loads(editorial.read_text()).get('brasil_maior_atividade_raios') or []
        highlights = [f"{x['cidade']} ({x['pais']})" for x in rows[:3] if x.get('cidade')]
    lines = [f'Boletim meteorológico de {when} (horário de Belém) para a América do Sul, com destaque para o Brasil.',
             '']
    if highlights:
        lines += ['Destaques de raios previstos: ' + ', '.join(highlights) + '.', '']
    lines += ['Neste boletim:',
              '• Chuva prevista pelo modelo ECENS',
              '• Previsão de raios por inteligência artificial com parâmetros convectivos do ECENS',
              '• Áreas com potencial de tempo severo',
              '• Nowcasting: condições observadas e monitoradas agora',
              '• Potencial de alagamento e extrapolação de raios para até duas horas',
              '• Recomendações à população',
              '',
              'A validade de cada previsão aparece na tela. Para alertas oficiais, consulte a Defesa Civil e o INMET.',
              'Apresentadora e voz geradas por inteligência artificial. Dados e mapas: Lightning Agent.',
              '',
              '#previsaodotempo #raios #chuva #Brasil']
    written = directory / 'youtube-metadata.json'
    if written.is_file():
        # The producer of this bulletin wrote its own title and description from the day's data.
        text = json.loads(written.read_text())
        title, lines = text['title'], [text['description']]
    status = {'privacyStatus': privacy, 'selfDeclaredMadeForKids': False,
              'containsSyntheticMedia': True}
    if publish_at is not None:
        if publish_at.tzinfo is None:
            raise ValueError('YOUTUBE_PUBLISH_AT deve incluir fuso horário')
        # The YouTube API accepts publishAt only for a private video.  It makes
        # the video public at the supplied instant without a worker remaining up.
        status['privacyStatus'] = 'private'
        status['publishAt'] = publish_at.astimezone(timezone.utc).isoformat().replace('+00:00', 'Z')
    return {'snippet': {'title': title.replace('<', '').replace('>', '')[:100],
                        'description': '\n'.join(lines)[:5000], 'tags': TAGS,
                        'categoryId': NEWS_CATEGORY, 'defaultLanguage': 'pt-BR',
                        'defaultAudioLanguage': 'pt-BR'},
            'status': status}


def upload(video: Path, metadata, token):
    size = video.stat().st_size
    headers, _ = _request(f'{UPLOAD}?uploadType=resumable&part=snippet,status',
                          data=json.dumps(metadata).encode(), method='POST',
                          headers={'Authorization': f'Bearer {token}',
                                   'Content-Type': 'application/json; charset=UTF-8',
                                   'X-Upload-Content-Type': 'video/mp4',
                                   'X-Upload-Content-Length': str(size)})
    session = headers.get('Location')
    if not session:
        raise YouTubeError('o YouTube não devolveu a sessão de upload')
    with video.open('rb') as stream:
        return _request(session, data=stream, method='PUT',
                        headers={'Authorization': f'Bearer {token}', 'Content-Type': 'video/mp4',
                                 'Content-Length': str(size)})[1]


def publish_bulletin(directory: Path, presented_at: datetime, env=os.environ, publish_at=None):
    """Upload `boletim.mp4` only when the token belongs to YOUTUBE_CHANNEL_ID."""
    video = directory / 'boletim.mp4'
    if not video.is_file():
        raise YouTubeError(f'vídeo não encontrado: {video}')
    missing = [k for k in ('YOUTUBE_CLIENT_ID', 'YOUTUBE_CLIENT_SECRET', 'YOUTUBE_REFRESH_TOKEN',
                           'YOUTUBE_CHANNEL_ID') if not env.get(k)]
    if missing:
        raise YouTubeError('configure ' + ', '.join(missing))
    token = access_token(env['YOUTUBE_CLIENT_ID'], env['YOUTUBE_CLIENT_SECRET'], env['YOUTUBE_REFRESH_TOKEN'])
    channel, name = authorized_channel(token)
    if channel != env['YOUTUBE_CHANNEL_ID']:
        raise YouTubeError(f'o token pertence ao canal {channel} ({name}), não a {env["YOUTUBE_CHANNEL_ID"]}')
    if publish_at is None and env.get('YOUTUBE_PUBLISH_AT'):
        try:
            publish_at = datetime.fromisoformat(env['YOUTUBE_PUBLISH_AT'].replace('Z', '+00:00'))
        except ValueError as exc:
            raise YouTubeError('YOUTUBE_PUBLISH_AT deve ser uma data ISO-8601 válida') from exc
    if publish_at is not None:
        if publish_at.tzinfo is None:
            raise YouTubeError('YOUTUBE_PUBLISH_AT deve incluir fuso horário')
        if publish_at <= datetime.now(timezone.utc):
            publish_at = None  # GitHub atrasou: publicar a previsão atual imediatamente.
    metadata = bulletin_metadata(directory, presented_at,
                                 timezone_name=env.get('VIDEO_TIMEZONE', 'America/Belem'),
                                 privacy=env.get('YOUTUBE_PRIVACY', 'private'), publish_at=publish_at)
    result = upload(video, metadata, token)
    if not result.get('id'):
        raise YouTubeError('YouTube não confirmou o identificador do vídeo')
    expected_privacy = metadata['status']['privacyStatus']
    actual_privacy = result.get('status', {}).get('privacyStatus')
    if actual_privacy != expected_privacy and not (
        publish_at is not None and actual_privacy == 'public' and publish_at <= datetime.now(timezone.utc)
    ):
        raise YouTubeError(f'YouTube respondeu com privacidade {actual_privacy!r}; esperado {expected_privacy!r}')
    record = {'video_id': result.get('id'), 'url': f"https://youtu.be/{result.get('id')}",
              'channel_id': channel, 'privacy': result.get('status', {}).get('privacyStatus'),
              'title': metadata['snippet']['title'],
              'scheduled_publish_at': metadata['status'].get('publishAt')}
    (directory / 'youtube.json').write_text(json.dumps(record, ensure_ascii=False, indent=2))
    return record


MAX_DAILY_ALERTS = 7
ALERT_TITLE = re.compile(r' \| \d{2}/\d{2} \d{2}:\d{2} #Shorts$')


def alerts_published_today(token, channel, now=None):
    """Alert Shorts already on the channel today (Brasília), read from YouTube itself.

    The channel is the only count every monitor shares. Bulletins and hand-made
    videos do not carry the alert title, so they never use up an alert's place.
    """
    headers = {'Authorization': f'Bearer {token}'}
    items = _request(f'{API}/channels?part=contentDetails&id={channel}', headers=headers)[1].get('items', [])
    uploads = items[0]['contentDetails']['relatedPlaylists']['uploads']
    videos = _request(f'{API}/playlistItems?part=snippet&maxResults=50&playlistId={uploads}', headers=headers)[1].get('items', [])
    zone = ZoneInfo('America/Sao_Paulo')
    today = (now or datetime.now(zone)).astimezone(zone).date()
    return sum(1 for video in videos
               if ALERT_TITLE.search(video['snippet'].get('title', ''))
               and datetime.fromisoformat(video['snippet']['publishedAt'].replace('Z', '+00:00')).astimezone(zone).date() == today)


def publish_short(directory: Path, env=os.environ, *, prefix='YOUTUBE', brand='TROVOX TEMPO'):
    """Publish a fresh approved-format city alert, recording the server's actual visibility."""
    from datetime import timezone
    import subprocess
    directory = Path(directory)
    saved = directory / 'youtube-short.json'
    if saved.exists():
        return json.loads(saved.read_text())
    report = json.loads((directory / 'alerta.json').read_text())
    started = datetime.fromisoformat(report['verificado_em'].replace('Z', '+00:00'))
    age = (datetime.now(timezone.utc) - started).total_seconds()
    if not 0 <= age <= 900:
        raise YouTubeError('alerta expirado: não publicar Short com mais de 15 minutos')
    if not report.get('gerar'):
        raise YouTubeError('Short sem gatilho de alerta confirmado')
    video = directory / 'short.mp4'
    probe = json.loads(subprocess.check_output(['ffprobe', '-v', 'error', '-show_streams', '-show_format', '-of', 'json', str(video)]))
    stream = next(x for x in probe['streams'] if x['codec_type'] == 'video')
    if stream['height'] <= stream['width'] or float(probe['format']['duration']) > 60:
        raise YouTubeError('Short deve ser vertical e ter até 60 segundos')
    privacy = env.get('SHORTS_YOUTUBE_PRIVACY', 'public')
    if privacy not in PRIVACY:
        raise ValueError('SHORTS_YOUTUBE_PRIVACY inválido')
    names = {key: f'{prefix}_{key}' for key in ('CLIENT_ID', 'CLIENT_SECRET', 'REFRESH_TOKEN', 'CHANNEL_ID')}
    missing = [name for name in names.values() if not env.get(name)]
    if missing:
        raise YouTubeError('configure ' + ', '.join(missing))
    token = access_token(env[names['CLIENT_ID']], env[names['CLIENT_SECRET']], env[names['REFRESH_TOKEN']])
    channel, name = authorized_channel(token)
    if channel != env[names['CHANNEL_ID']]:
        raise YouTubeError('o token pertence a outro canal; upload recusado')
    if prefix == 'YOUTUBE':
        # Unknown count means no upload: the cap must hold even when the check fails.
        try:
            published = alerts_published_today(token, channel)
        except Exception as exc:
            raise QuotaExceeded(f'contagem diária de alertas indisponível: {exc}') from exc
        if published >= MAX_DAILY_ALERTS:
            raise QuotaExceeded(f'limite diário de {MAX_DAILY_ALERTS} alertas do canal atingido')
    local = started.astimezone(ZoneInfo(report.get('timezone','America/Sao_Paulo')))
    label = 'risco de alagamento' if report.get('secao') == 'alagamentos-sp' else 'alerta de tempestade'
    from .city_shorts import lightning_hook
    count = None if report.get('secao') == 'alagamentos-sp' else lightning_hook(report.get('raios'))
    stamp = f" | {local:%d/%m %H:%M} #Shorts"   # ALERT_TITLE counts the daily alerts by this ending
    title = f"{report['nome']} ({report['uf']}): {label}{stamp}"
    if count:
        for news in (f"{count} raios em 30 min perto de {report['nome']} ({report['uf']}): {label}",
                     f"{count} raios em 30 min perto de {report['nome']} ({report['uf']})"):
            if len(news + stamp) <= 100:
                title = news + stamp
                break
    title = report.get('titulo_short') or title
    link = 'https://www.youtube.com/@trovoxtempo?sub_confirmation=1'
    ask = ask_es = ''
    if brand == 'TROVOX TEMPO':
        ask = ('⚡ Choveu forte aí? Conte nos comentários!\n'
               f'🔔 Inscreva-se para receber o próximo alerta antes da tempestade chegar: {link}\n\n')
        ask_es = ('⚡ ¿Llueve fuerte donde usted está? ¡Cuéntenos en los comentarios!\n'
                  f'🔔 Suscríbase para recibir la próxima alerta antes de que llegue la tormenta: {link}\n\n')
    language = report.get('idioma', 'pt-BR')
    description = (ask + f"{brand} — atualização de {local:%d/%m/%Y às %H:%M}, horário local.\n"
        + report['roteiro'] + '\n\nNowcasting regional, não é aviso oficial. Consulte a Defesa Civil e o INMET.'
        + '\nApresentadora e voz geradas por IA. Dados: Lightning Agent. Mapa: © OpenStreetMap contributors — https://www.openstreetmap.org/copyright'
        + '\n#Shorts #previsaodotempo #raios #nowcasting')
    metadata = {'snippet': {'title': title[:100], 'description': description[:5000],
        'categoryId': NEWS_CATEGORY, 'defaultLanguage': language, 'defaultAudioLanguage': language,
        'tags': ['Shorts', report['nome'], 'nowcasting', 'chuva', brand]},
        'status': {'privacyStatus': privacy, 'selfDeclaredMadeForKids': False, 'containsSyntheticMedia': True}}
    if language.startswith('en'):
        metadata['snippet'].update(
            title=title[:100], defaultLanguage=language, defaultAudioLanguage=language,
            tags=['Shorts', report['nome'], report.get('pais', report['uf']), 'rain', 'nowcasting', brand],
            description=(f"{brand} — update for {local:%Y-%m-%d %H:%M}, local time.\n" + report['roteiro']
                + '\n\nAutomated regional estimate, not an official warning. Check your local weather service.'
                + '\nAI-generated narration. Data: Open-Meteo.'
                + '\n#Shorts #rain #weather #nowcasting'))
    elif language.startswith('es'):
        place = f"{report['nome']}, {report.get('pais', report['uf'])}"
        title = f"{place}: alerta de tormenta{stamp}"
        if count and len(f"¡{count} rayos en 30 min cerca de {place}! Alerta de tormenta{stamp}") <= 100:
            title = f"¡{count} rayos en 30 min cerca de {place}! Alerta de tormenta{stamp}"
        metadata['snippet'].update(title=title[:100], defaultLanguage=report['idioma'], defaultAudioLanguage=report['idioma'],
            tags=['Shorts',report['nome'],report.get('pais',report['uf']),'tormentas','rayos','TROVOX TEMPO'],
            description=(ask_es + f"TROVOX TEMPO — {local:%d/%m/%Y %H:%M}, hora local.\n" + report['roteiro']
            + '\nEstimación regional. Consulte al servicio meteorológico y Protección Civil de su país.'
            + '\nPresentadora y voz generadas por IA. Datos: Lightning Agent. Mapa: © OpenStreetMap contributors — https://www.openstreetmap.org/copyright'
            + '\n#Shorts #tormentas #rayos'))
    result = upload(video, metadata, token)
    if not result.get('id'):
        raise YouTubeError('upload sem identificador de vídeo')
    record = {'video_id': result['id'], 'url': 'https://www.youtube.com/shorts/' + result['id'],
              'channel_id': channel, 'privacy': result.get('status', {}).get('privacyStatus'), 'title': title[:100]}
    saved.write_text(json.dumps(record, ensure_ascii=False, indent=2))
    return record
