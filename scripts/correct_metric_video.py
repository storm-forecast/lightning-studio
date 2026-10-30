#!/usr/bin/env python3
"""Correct narration/map metric mismatches without changing speech or lip timing.

Only reuse archived speech when the captured forecast version and valid window
still match. Otherwise regenerate a new bulletin from fresh data.
"""
import argparse
from pathlib import Path
import json
import shutil
import subprocess
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from lightning_video_engine.app.segments import Segment,save_plan
from lightning_video_engine.app.forecast_policy import narration_view,validate_forecast_text,validate_forecasts
from lightning_video_engine.app.directed_scenes import capture_segments
from lightning_video_engine.app.production import stamp


def correct(source,destination,app_url):
    source=source.resolve();destination=destination.resolve()
    if source==destination:raise ValueError('use outro diretório; o original será preservado')
    scenes=[Segment(**s) for s in json.loads((source/'plano-cenas.json').read_text())]
    destination.mkdir(parents=True,exist_ok=True);images=destination/'cenas';images.mkdir(exist_ok=True)
    corrected=[]
    for s in scenes:
        expected=narration_view(s)
        previous=dict(s.metadata)
        old=s.view
        original_image=Path(s.image)
        s.image=str(images/f'{s.id}.png')
        if expected!=old and s.available:
            s.view=expected
            label='Probabilidade de raios' if expected=='probabilidade' else 'Quantidade prevista de raios'
            s.title=label+' | '+(s.place['nome'] if s.place else 'IA com parâmetros convectivos do ECENS')
            capture_segments(app_url,[s],images)
            if not s.available:raise RuntimeError(f'{s.id}: captura indisponível; não substituir por imagem antiga')
            before=previous.get('map',{});after=s.metadata.get('map',{})
            for key in ('versao','janelas'):
                if not before.get(key) or before[key]!=after.get(key):
                    raise RuntimeError(f'{s.id}: rodada/período mudou; gerar um novo boletim com dados atualizados')
            stamp(s)
            corrected.append({'id':s.id,'from':old,'to':expected,'start':s.start,'end':s.end,'image':s.image})
        else:
            shutil.copy2(original_image,s.image)
        validate_forecast_text(s)
    validate_forecasts(scenes)
    save_plan(scenes,destination/'plano-cenas.json')
    if not corrected:raise RuntimeError('não há divergência de métrica para corrigir neste vídeo')
    cmd=['ffmpeg','-y','-v','warning','-filter_complex_threads','1','-i',str(source/'boletim.mp4')]
    for item in corrected:cmd+=['-loop','1','-framerate','25','-i',item['image']]
    graph=[];current='0:v'
    for i,item in enumerate(corrected,1):
        label=f'corrected{i}'
        graph.append(f'[{current}][{i}:v]overlay=32:144:enable=\'gte(t,{item["start"]:.6f})*lt(t,{item["end"]:.6f})\':shortest=1[{label}]')
        current=label
    cmd+=['-filter_complex',';'.join(graph),'-map',f'[{current}]','-map','0:a:0','-c:a','copy',
          '-c:v','libx264','-preset','veryfast','-crf','21','-maxrate','5M','-bufsize','10M',
          '-threads','2','-pix_fmt','yuv420p','-movflags','+faststart',str(destination/'boletim.mp4')]
    subprocess.run(cmd,check=True,timeout=1800)
    (destination/'correcoes.json').write_text(json.dumps({'original':str(source/'boletim.mp4'),
         'audio':'original preservado sem recodificação','changes':corrected},ensure_ascii=False,indent=2)+'\n')
    (destination/'roteiro.md').write_text('\n\n'.join(f'## {s.title} ({s.start:.2f}–{s.end:.2f}s)\n\n{s.narration}' for s in scenes))
    print(destination/'boletim.mp4')

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--source',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True);p.add_argument('--app-url',default='https://lightning-agent.onrender.com/app/')
    args=p.parse_args();correct(args.source,args.output,args.app_url)
