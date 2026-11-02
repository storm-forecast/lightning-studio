#!/usr/bin/env python3
"""Scan cheaply, then run finite synchronous Shorts jobs in GitHub Actions."""
import argparse
import json
import os
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from lightning_video_engine.app.city_shorts import AgentSource,CITIES,Monitor
from lightning_video_engine.app.sp_flood_shorts import SP_FLOOD_CITIES
from lightning_video_engine.app.sp_flood_zones import confirmed_zones
from lightning_video_engine.app.youtube import quota_blocked_until

p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--scan',action='store_true')
a=p.parse_args()
root=Path(os.environ.get('SHORTS_OUTPUT_DIR','output/shorts'))
source=AgentSource(os.environ.get('LIGHTNING_API_URL','https://lightning-agent.onrender.com'))
monitor=Monitor(source,root)
until=quota_blocked_until(root)
if until:
    # Quota exhausted: stop scanning and rendering until YouTube renews it.
    (root/'scan.json').write_text(json.dumps({'candidatas':[],'relatorios':{},'erros':[],'quota_esgotada_ate':until.isoformat()},ensure_ascii=False,indent=2))
    if os.environ.get('GITHUB_OUTPUT'):
        with open(os.environ['GITHUB_OUTPUT'],'a') as output:output.write('has_alerts=false\n')
    print('Quota do YouTube esgotada até',until.isoformat(),'— monitor parado.',flush=True)
    raise SystemExit(0)
if a.scan:
    candidates=[];reports={};errors=[]
    flood_areas=[]
    flood_file=root/'flood-areas.json'
    if flood_file.exists():
        flood_areas=json.loads(flood_file.read_text())
    for key in CITIES:
        try:
            if monitor.eligible(key):
                report=monitor.evaluate_city(key)
                if key in SP_FLOOD_CITIES and flood_areas:
                    name,state,_,_=CITIES[key]
                    zones=confirmed_zones(source,name,state,flood_areas)
                    if zones:
                        report['flood_zones']=zones
                        report['zona_id']=zones[0]['zona_id']
                        report['gerar']=True
                        report['motivos']=['polígono oficial de potencial de alagamento associado ao município']
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
        if quota_blocked_until(root):
            # Do not render videos that can no longer be uploaded today.
            item.update(estado='falhou',erro='quota do YouTube esgotada; não renderizado')
            monitor.save(item)
            continue
        Monitor.work(monitor,item,recheck=False)
        item=monitor.get(ident)
        print(report['cidade'],item['estado'],json.dumps(item.get('youtube',{}),ensure_ascii=False),flush=True)
        youtube=item.get('youtube',{})
        if item['estado']=='falhou' or (youtube.get('error') and not youtube.get('quota')):failed=True
    if failed:raise SystemExit('Uma ou mais cidades falharam; consulte os artefatos')
