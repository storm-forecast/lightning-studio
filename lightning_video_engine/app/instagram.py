"""Instagram Reels publishing (standard library only).

Accepts both token kinds the Meta app can issue: an Instagram Login token
(``IG...``, graph.instagram.com) or a unified-login system user token
(``EAA...``, graph.facebook.com, never expires).  The app stays in development
mode with the account as Instagram Tester, so no App Review or paid service is involved.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

VERSION = os.environ.get('INSTAGRAM_API_VERSION', 'v23.0')
RUPLOAD = f'https://rupload.facebook.com/ig-api-upload/{VERSION}'
CAPTION_LIMIT = 2200


class InstagramError(RuntimeError):
    pass


def _request(url, *, data=None, headers=None, method=None):
    request = urllib.request.Request(url, data=data, headers=headers or {}, method=method)
    try:
        with urllib.request.urlopen(request, timeout=600) as response:
            body = response.read()
            return json.loads(body) if body else {}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors='replace')
        raise InstagramError(f'HTTP {exc.code} em {url.split("?")[0]}: {detail[:500]}') from exc


def _host(token):
    return 'graph.instagram.com' if token.startswith('IG') else 'graph.facebook.com'


def _graph(path, token, method='GET', **params):
    query = urllib.parse.urlencode({**params, 'access_token': token})
    base = f'https://{_host(token)}/{VERSION}'
    if method == 'GET':
        return _request(f'{base}/{path}?{query}')
    return _request(f'{base}/{path}', data=query.encode(), method=method,
                    headers={'Content-Type': 'application/x-www-form-urlencoded'})


def authorized_account(token, account=None):
    """The professional account id and username the token can publish to."""
    if account:
        # Fails with HTTP 400 when the token has no access to this account.
        return account, _graph(account, token, fields='username').get('username', '')
    if token.startswith('IG'):
        me = _graph('me', token, fields='user_id,username')
        if me.get('user_id'):
            return me['user_id'], me.get('username', '')
    else:
        pages = _graph('me/accounts', token, fields='instagram_business_account{id,username}').get('data', [])
        linked = [page['instagram_business_account'] for page in pages if page.get('instagram_business_account')]
        if linked:
            return linked[0]['id'], linked[0].get('username', '')
    raise InstagramError('não encontrei a conta do Instagram deste token; configure INSTAGRAM_USER_ID')


def refresh_token(token):
    """Extend a long-lived token for another 60 days (it must be at least 24 hours old)."""
    query = urllib.parse.urlencode({'grant_type': 'ig_refresh_token', 'access_token': token})
    return _request(f'https://graph.instagram.com/refresh_access_token?{query}')


def publish_reel(video: Path, caption: str, env=os.environ, *, share_to_feed=True, wait=600):
    """Upload a local MP4 as a Reel and publish it; returns id, permalink and account."""
    video = Path(video)
    if not video.is_file():
        raise InstagramError(f'vídeo não encontrado: {video}')
    token = env.get('INSTAGRAM_ACCESS_TOKEN')
    if not token:
        raise InstagramError('configure INSTAGRAM_ACCESS_TOKEN')
    account, username = authorized_account(token, env.get('INSTAGRAM_USER_ID'))
    container = _graph(f'{account}/media', token, method='POST', media_type='REELS', upload_type='resumable',
                       caption=caption[:CAPTION_LIMIT], share_to_feed='true' if share_to_feed else 'false')['id']
    size = video.stat().st_size
    with video.open('rb') as stream:
        uploaded = _request(f'{RUPLOAD}/{container}', data=stream, method='POST',
                            headers={'Authorization': f'OAuth {token}', 'offset': '0',
                                     'file_size': str(size), 'Content-Length': str(size)})
    if not uploaded.get('success'):
        raise InstagramError(f'o Instagram recusou o arquivo: {uploaded}')
    # Instagram transcodes the Reel before it can be published.
    deadline = time.monotonic() + wait
    while True:
        state = _graph(container, token, fields='status_code,status')
        if state.get('status_code') == 'FINISHED':
            break
        if state.get('status_code') in {'ERROR', 'EXPIRED'}:
            raise InstagramError(f"processamento do Reel falhou: {state.get('status')}")
        if time.monotonic() > deadline:
            raise InstagramError('o Instagram não terminou de processar o Reel a tempo')
        time.sleep(10)
    media = _graph(f'{account}/media_publish', token, method='POST', creation_id=container)['id']
    permalink = _graph(media, token, fields='permalink').get('permalink')
    return {'media_id': media, 'url': permalink, 'account_id': account, 'username': username}


def publish_short(directory: Path, env=os.environ):
    """Publish a rendered alert Short (short.mp4 + alerta.json) once, recording the result."""
    directory = Path(directory)
    saved = directory / 'instagram.json'
    if saved.exists():
        return json.loads(saved.read_text())
    report = json.loads((directory / 'alerta.json').read_text())
    language = report.get('idioma', 'pt-BR')
    # The caption carries the alert time, so a late repost is never read as a current warning.
    checked = datetime.fromisoformat(report['verificado_em'].replace('Z', '+00:00')) if report.get('verificado_em') else None
    local = checked.astimezone(ZoneInfo(report.get('timezone', 'America/Sao_Paulo'))) if checked else None
    when = f' | {local:%d/%m %H:%M}' if local else ''
    if language.startswith('pt'):
        footer = ('\n\nNowcasting regional, não é aviso oficial. Consulte a Defesa Civil e o INMET.'
                  '\nApresentadora e voz geradas por IA. Dados: Lightning Agent.'
                  '\n#previsaodotempo #raios #chuva #nowcasting')
        label = 'risco de alagamento' if report.get('secao') == 'alagamentos-sp' else 'alerta de tempestade'
        heading = report.get('titulo_short') or f"{report['nome']}: {label}{when} (horário local)"
    elif language.startswith('es'):
        footer = ('\n\nEstimación regional, no es un aviso oficial. Consulte al servicio meteorológico y Protección Civil de su país.'
                  '\nPresentadora y voz generadas por IA. Datos: Lightning Agent.'
                  '\n#tormentas #rayos #clima #nowcasting')
        heading = f"{report['nome']}, {report.get('pais', report.get('uf', ''))}: alerta de tormenta{when} (hora local)"
    else:
        footer = '\n\nAI-generated presenter and voice. Data: Lightning Agent.\n#weather #storm #nowcasting'
        heading = report.get('titulo_short') or f"{report['nome']}: storm alert{when} (local time)"
    caption = heading.replace('#Shorts', '').strip() + '\n\n' + report['roteiro'] + footer
    record = publish_reel(directory / 'short.mp4', caption, env)
    saved.write_text(json.dumps(record, ensure_ascii=False, indent=2))
    return record


_warned_missing_token = False


def cross_post(directory: Path, env=os.environ):
    """Repeat a published YouTube Short on Instagram; never raises, so YouTube results are kept."""
    global _warned_missing_token
    if not env.get('INSTAGRAM_ACCESS_TOKEN'):
        # Said once per process, so a missing secret is visible in the logs without repeating every pass.
        if not _warned_missing_token:
            print('Instagram desativado: INSTAGRAM_ACCESS_TOKEN não configurado', flush=True)
            _warned_missing_token = True
        return None
    try:
        return publish_short(directory, env)
    except Exception as exc:
        return {'error': str(exc)}
