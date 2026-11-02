#!/usr/bin/env python3
"""Publish a rendered video as an Instagram Reel, or check/refresh the access token."""
import argparse
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parents[1] / '.env')
import os
from lightning_video_engine.app.instagram import authorized_account, publish_reel, publish_short, refresh_token

p = argparse.ArgumentParser(description=__doc__)
g = p.add_mutually_exclusive_group(required=True)
g.add_argument('--directory', type=Path, help='Short directory containing short.mp4 and alerta.json')
g.add_argument('--video', type=Path, help='any MP4 file; use with --caption')
g.add_argument('--check', action='store_true', help='show which account the token belongs to')
g.add_argument('--refresh', action='store_true', help='print a renewed 60-day token')
p.add_argument('--caption', default='')
a = p.parse_args()

if a.check:
    account, username = authorized_account(os.environ['INSTAGRAM_ACCESS_TOKEN'], os.environ.get('INSTAGRAM_USER_ID'))
    print(f'Token válido para @{username} (INSTAGRAM_USER_ID={account})')
elif a.refresh:
    renewed = refresh_token(os.environ['INSTAGRAM_ACCESS_TOKEN'])
    print('Novo INSTAGRAM_ACCESS_TOKEN (expira em', renewed['expires_in'] // 86400, 'dias):')
    print(renewed['access_token'])
else:
    record = publish_short(a.directory) if a.directory else publish_reel(a.video, a.caption)
    print('Publicado no Instagram:', record['url'])
