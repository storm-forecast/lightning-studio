#!/usr/bin/env python3
"""Scan cheaply, then run finite synchronous Shorts jobs in GitHub Actions."""
import argparse
import json
import os
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from lightning_video_engine.app.city_shorts import AgentSource,CITIES
from lightning_video_engine.app.shorts_runs import DeferredMonitor,publish_cities,scan_cities

p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--scan',action='store_true')
a=p.parse_args()
root=Path(os.environ.get('SHORTS_OUTPUT_DIR','output/shorts'))
source=AgentSource(os.environ.get('LIGHTNING_API_URL','https://lightning-agent.onrender.com'))
monitor=DeferredMonitor(source,root)
if a.scan:
    flood_file=root/'flood-areas.json'
    scan=scan_cities(monitor,source,json.loads(flood_file.read_text()) if flood_file.exists() else [])
    (root/'scan.json').write_text(json.dumps(scan,ensure_ascii=False,indent=2))
    if os.environ.get('GITHUB_OUTPUT'):
        with open(os.environ['GITHUB_OUTPUT'],'a') as output:output.write('has_alerts='+str(bool(scan['candidatas'])).lower()+'\n')
    print('Cidades com alerta confirmado:',', '.join(scan['candidatas']) or 'nenhuma',flush=True)
    if scan['erros']:print('Falhas de consulta:',json.dumps(scan['erros'],ensure_ascii=False),flush=True)
    if len(scan['erros'])==len(CITIES):raise SystemExit('Todas as consultas falharam')
else:
    scan=json.loads((root/'scan.json').read_text())
    lines,failed=publish_cities(monitor,root,scan['relatorios'])
    for line in lines:print(line,flush=True)
    if failed:raise SystemExit('Uma ou mais cidades falharam; consulte os artefatos')
