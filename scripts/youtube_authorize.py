#!/usr/bin/env python3
"""One-time local OAuth consent; prints the refresh token to store as a secret.

Uso: python scripts/youtube_authorize.py --client-secret client_secret.json [--env-file .env]
Entre com a conta dona do canal (ou escolha a Conta de Marca correta).
"""
import argparse
import http.server
import json
import secrets
import sys
import urllib.parse
import webbrowser
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lightning_video_engine.app.youtube import AUTH_URL, SCOPES, access_token, authorized_channel, exchange_token

p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
p.add_argument('--client-secret', type=Path, required=True, help='JSON de credencial OAuth "App para computador"')
p.add_argument('--env-file', type=Path, help='grava as variáveis neste arquivo em vez de mostrar o token')
a = p.parse_args()
config = json.loads(a.client_secret.read_text())
config = config.get('installed') or config.get('web') or config
client_id, client_secret = config['client_id'], config['client_secret']
state, received = secrets.token_urlsafe(16), {}


class Callback(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        received.update(urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query))
        self.send_response(200)
        self.send_header('Content-Type', 'text/plain; charset=utf-8')
        self.end_headers()
        self.wfile.write('Autorização recebida. Pode fechar esta aba.'.encode())

    def log_message(self, *args):
        pass


server = http.server.HTTPServer(('127.0.0.1', 0), Callback)
redirect = f'http://127.0.0.1:{server.server_port}'
url = AUTH_URL + '?' + urllib.parse.urlencode({
    'client_id': client_id, 'redirect_uri': redirect, 'response_type': 'code', 'scope': ' '.join(SCOPES),
    'access_type': 'offline', 'prompt': 'consent', 'state': state})
print('Abra no navegador, se não abrir sozinho:\n' + url, flush=True)
webbrowser.open(url)
while 'code' not in received and 'error' not in received:
    server.handle_request()
if received.get('state', [''])[0] != state or 'error' in received:
    sys.exit(f'autorização recusada: {received.get("error", ["state inválido"])[0]}')
tokens = exchange_token(client_id, client_secret, code=received['code'][0],
                        redirect_uri=redirect, grant_type='authorization_code')
if 'refresh_token' not in tokens:
    sys.exit('o Google não devolveu refresh token; revogue o acesso em myaccount.google.com/permissions e repita')
channel, name = authorized_channel(access_token(client_id, client_secret, tokens['refresh_token']))
print(f'\nCanal autorizado: {name} ({channel})')
values = {'YOUTUBE_CLIENT_ID': client_id, 'YOUTUBE_CLIENT_SECRET': client_secret,
          'YOUTUBE_REFRESH_TOKEN': tokens['refresh_token'], 'YOUTUBE_CHANNEL_ID': channel}
if a.env_file:
    kept = [line for line in (a.env_file.read_text().splitlines() if a.env_file.is_file() else [])
            if line.split('=', 1)[0] not in values]
    a.env_file.write_text('\n'.join(kept + [f'{k}={v}' for k, v in values.items()]) + '\n')
    a.env_file.chmod(0o600)
    print(f'Variáveis gravadas em {a.env_file}')
else:
    print('Salve como secrets do repositório:')
    print('\n'.join(f'  {k}={v}' for k, v in values.items()))
