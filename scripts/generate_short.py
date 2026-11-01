#!/usr/bin/env python3
"""Local live-data alert test. Never uploads to YouTube."""
import argparse
import json
import os
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lightning_video_engine.app.city_shorts import AgentSource, CITIES, evaluate, render

p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--city', required=True, choices=sorted(CITIES))
p.add_argument('--directory', required=True, type=Path)
p.add_argument('--api', default=os.environ.get('LIGHTNING_API_URL','https://lightning-agent.onrender.com'))
a=p.parse_args()
source=AgentSource(a.api)
report=evaluate(a.city,source)
print(json.dumps(report,ensure_ascii=False,indent=2))
if report['gerar']:
    render(a.directory,report,source)
    print(a.directory/'short.mp4')
else:
    print('Sem gatilho de alerta atual: nenhum vídeo gerado.')
