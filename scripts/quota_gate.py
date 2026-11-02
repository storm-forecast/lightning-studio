#!/usr/bin/env python3
"""Tell a workflow to stop while a Shorts folder records an exhausted YouTube quota.

Standard library only: it runs before any dependency is installed.
"""
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

root = Path(sys.argv[1])
try:
    until = datetime.fromisoformat(json.loads((root / 'quota.json').read_text())['ate'])
except (OSError, ValueError, KeyError, TypeError):
    until = None
blocked = bool(until and datetime.now(timezone.utc) < until)
if os.environ.get('GITHUB_OUTPUT'):
    with open(os.environ['GITHUB_OUTPUT'], 'a') as output:
        output.write(f'blocked={str(blocked).lower()}\n')
print(f'Quota do YouTube esgotada até {until.isoformat()}; monitor parado.' if blocked else 'Quota do YouTube disponível.', flush=True)
