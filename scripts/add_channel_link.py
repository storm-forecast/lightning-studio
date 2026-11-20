#!/usr/bin/env python3
"""Put the TROVOX TEMPO channel link on top of the description of every video already published.

Each edit costs 50 units of the 10,000-unit daily YouTube quota (an upload costs 1,600), so at most
--max videos are edited per run; videos that already carry the link are skipped, and the next run
continues where this one stopped. Needs a refresh token authorized with the youtube.force-ssl scope
(run scripts/youtube_authorize.py again).

Uso: python scripts/add_channel_link.py [--max 60] [--dry-run]
"""
import argparse
import json
import os
import sys
import urllib.parse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / '.env')
from lightning_video_engine.app.youtube import (API, CHANNEL_URL, TEMPO_CHANNEL_ID, YouTubeError, _request,
                                                access_token, authorized_channel, with_channel_link)

p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
p.add_argument('--max', type=int, default=60, help='máximo de vídeos editados nesta rodada (50 unidades cada)')
p.add_argument('--dry-run', action='store_true', help='só lista o que seria editado')
a = p.parse_args()

env = os.environ
token = access_token(env['YOUTUBE_CLIENT_ID'], env['YOUTUBE_CLIENT_SECRET'], env['YOUTUBE_REFRESH_TOKEN'])
channel, name = authorized_channel(token)
if channel != TEMPO_CHANNEL_ID:
    raise SystemExit(f'o token é do canal {name} ({channel}), não do TROVOX TEMPO')
auth = {'Authorization': f'Bearer {token}'}


def get(path, **query):
    return _request(f'{API}/{path}?{urllib.parse.urlencode(query)}', headers=auth)[1]


uploads = get('channels', part='contentDetails', id=channel)['items'][0]['contentDetails']['relatedPlaylists']['uploads']
ids, page = [], None
while True:
    query = dict(part='contentDetails', playlistId=uploads, maxResults=50)
    if page:
        query['pageToken'] = page
    result = get('playlistItems', **query)
    ids += [item['contentDetails']['videoId'] for item in result.get('items', [])]
    page = result.get('nextPageToken')
    if not page:
        break

pending = []
for k in range(0, len(ids), 50):
    for video in get('videos', part='snippet', id=','.join(ids[k:k + 50])).get('items', []):
        if CHANNEL_URL not in video['snippet'].get('description', ''):
            pending.append(video)
print(f'{len(ids)} vídeos no canal; {len(pending)} sem o link do canal')

done = 0
for video in pending[:a.max]:
    snippet = video['snippet']
    # videos.update replaces the whole snippet: send back every editable field as it is.
    body = {'id': video['id'], 'snippet': {key: snippet[key] for key in
            ('title', 'categoryId', 'tags', 'defaultLanguage', 'defaultAudioLanguage') if key in snippet}}
    body['snippet']['description'] = with_channel_link(snippet.get('description'))
    if a.dry_run:
        print('editaria', video['id'], snippet['title'][:70])
        continue
    try:
        _request(f'{API}/videos?part=snippet', data=json.dumps(body).encode(), method='PUT',
                 headers={**auth, 'Content-Type': 'application/json; charset=UTF-8'})
    except YouTubeError as exc:
        if 'quota' in str(exc).lower():
            print('Cota diária do YouTube esgotada; rode de novo amanhã.')
            break
        if 'insufficient' in str(exc).lower() or '403' in str(exc):
            raise SystemExit('Sem permissão para editar: autorize de novo com scripts/youtube_authorize.py '
                             '(escopo youtube.force-ssl).') from exc
        print('falhou', video['id'], str(exc)[:200])
        continue
    done += 1
    print('ok', video['id'], snippet['title'][:70])
print(f'{done} descrições editadas; faltam {len(pending) - done}')
