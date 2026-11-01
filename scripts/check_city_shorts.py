#!/usr/bin/env python3
"""Scan cheaply, then run finite synchronous Shorts jobs in GitHub Actions."""
import argparse
import json
import os
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from lightning_video_engine.app.city_shorts import AgentSource,CITIES,Monitor

p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--scan',action='store_true')
a=p.parse_args()
root=Path(os.environ.get('SHORTS_OUTPUT_DIR','output/shorts'))
source=AgentSource(os.environ.get('LIGHTNING_API_URL','https://lightning-agent.onrender.com'))
monitor=Monitor(source,root)
if a.scan:
    candidates=[];reports={};errors=[]
    for key in CITIES:
        try:
            if monitor.eligible(key):
                report=monitor.evaluate_city(key)
                if report['gerar']:
                    candidates.append(key)
                    reports[key]=report
        except Exception as exc:errors.append({'cidade':key,'erro':str(exc)})
    (root/'scan.json').write_text(json.dumps({'candidatas':candidates,'relatorios':reports,'erros':errors},ensure_ascii=False,indent=2))
    if os.environ.get('GITHUB_OUTPUT'):
        with open(os.environ['GITHUB_OUTPUT'],'a') as output:output.write('has_alerts='+str(bool(candidates)).lower()+'\n')
    print('Cidades com alerta confirmado:',', '.join(candidates) or 'nenhuma',flush=True)
    if errors:print('Falhas de consulta:',json.dumps(errors,ensure_ascii=False),flush=True)
    if len(errors)==len(CITIES):raise SystemExit('Todas as consultas falharam')
else:
    # Persist the intent before encoding; avoid daemon threads exiting with the CLI.
    class Sequential(Monitor):
        def work(self,item):
            self.pending.append(item)
    monitor=Sequential(source,root)
    monitor.pending=[]
    scan=json.loads((root/'scan.json').read_text())
    result=monitor.check(reports=scan['relatorios'])
    # check dispatches daemon callbacks; collect IDs directly from the persisted report.
    failed=False
    for report in result['resultados']:
        if report.get('erro'):failed=True
        ident=report.get('video_id')
        if not ident:continue
        item=monitor.get(ident)
        Monitor.work(monitor,item,recheck=False)
        item=monitor.get(ident)
        print(report['cidade'],item['estado'],json.dumps(item.get('youtube',{}),ensure_ascii=False),flush=True)
        if item['estado']=='falhou' or item.get('youtube',{}).get('error'):failed=True
    if failed:raise SystemExit('Uma ou mais cidades falharam; consulte os artefatos')
