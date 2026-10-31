#!/usr/bin/env python3
"""Upload a produced bulletin to the configured YouTube channel."""
import argparse
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lightning_video_engine.app.youtube import QuotaExceeded, publish_bulletin

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--directory', type=Path, required=True)
a = p.parse_args()
# Workflow directories are named trovox-YYYYMMDDTHHMMSSZ at generation start.
match = re.search(r'(\d{8}T\d{6}Z)', a.directory.name)
started = (datetime.strptime(match.group(1), '%Y%m%dT%H%M%SZ').replace(tzinfo=timezone.utc) if match
           else datetime.fromtimestamp((a.directory / 'boletim.mp4').stat().st_mtime, timezone.utc))
try:
    record = publish_bulletin(a.directory, started)
except QuotaExceeded as exc:
    # The bulletin stays in the workflow artifact; a quota stop is not a render failure.
    print(f'::warning::upload não enviado: {exc}')
    sys.exit(0)
print('Publicado:', record['url'], f"({record['privacy']})")
