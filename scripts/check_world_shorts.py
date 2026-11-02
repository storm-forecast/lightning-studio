#!/usr/bin/env python3
"""Publish at most one high-condition global rain Short per city per UTC day."""
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lightning_video_engine.app.world_shorts import candidates, report, render
from lightning_video_engine.app.youtube import QuotaExceeded, block_quota, publish_short, quota_blocked_until

root = Path(os.environ.get('WORLD_SHORTS_OUTPUT_DIR', 'output/world-shorts'))
root.mkdir(parents=True, exist_ok=True)
history_file = root / 'published.json'
history = json.loads(history_file.read_text()) if history_file.exists() else {}
until = quota_blocked_until(root)
if until:
    print('Quota do YouTube esgotada até', until.isoformat(), '— monitor parado.', flush=True)
    raise SystemExit(0)
today = datetime.now(timezone.utc).date().isoformat()
rows = [row for row in candidates() if history.get(row['id']) != today]
requested = os.environ.get('WORLD_CITY', '').strip().lower()
if requested:
    wanted = {value.strip() for value in requested.split(',') if value.strip()}
    rows = [row for row in rows if row['id'] in wanted]
if not rows:
    print('Nenhuma condição global alta nova para a cidade solicitada.', flush=True)
    raise SystemExit(0)
limit = 2 if requested else 1
for row in rows[:limit]:
    item = report(row)
    directory = root / f"{item['cidade']}-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}"
    render(directory, item)
    try:
        saved = publish_short(directory, prefix='WORLD_YOUTUBE', brand='TROVOX GLOBAL')
    except QuotaExceeded as exc:
        until = block_quota(root, str(exc))
        print('Quota do YouTube esgotada até', until.isoformat(), '— monitor parado.', flush=True)
        break
    history[item['cidade']] = today
    print('Published:', saved['url'], flush=True)
history_file.write_text(json.dumps(history, ensure_ascii=False, indent=2))
