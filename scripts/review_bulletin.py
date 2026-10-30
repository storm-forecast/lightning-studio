#!/usr/bin/env python3
"""Verify exported map frames against their audio-timed scene images."""
import argparse
import json
from pathlib import Path
import subprocess
from PIL import Image, ImageChops, ImageStat

p=argparse.ArgumentParser(description=__doc__);p.add_argument('directory',type=Path);args=p.parse_args()
root=args.directory.resolve();video=root/'boletim.mp4'
plan=json.loads((root/'plano-cenas.json').read_text())
probe=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_streams','-show_format','-of','json',str(video)]))
duration=float(probe['format']['duration']);expected=plan[-1]['end']
assert abs(duration-expected)<.08,(duration,expected)
results=[]
for s in plan:
    ref=Image.open(s['image']).convert('RGB').resize((144,81))
    for timestamp in (s['start']+.08,s['end']-.08):
        data=subprocess.check_output(['ffmpeg','-v','error','-ss',f'{timestamp:.6f}',
            '-i',str(video),'-threads','2','-vf','crop=1440:810:32:144,scale=144:81',
            '-frames:v','1','-f','rawvideo','-pix_fmt','rgb24','-'])
        frame=Image.frombytes('RGB',(144,81),data)
        error=sum(ImageStat.Stat(ImageChops.difference(frame,ref)).mean)/3
        results.append({'scene':s['id'],'time':round(timestamp,3),'mean_rgb_error':round(error,3)})
        assert error<12,(s['id'],timestamp,error)
subprocess.run(['ffmpeg','-v','error','-threads','2','-i',str(video),'-f','null','-'],check=True)
report={'duration':duration,'expected_duration':expected,'scenes':len(plan),'checked_frames':results,
        'width':next(s['width'] for s in probe['streams'] if s['codec_type']=='video'),
        'height':next(s['height'] for s in probe['streams'] if s['codec_type']=='video'),
        'size_bytes':int(probe['format']['size']),'decode':'ok'}
(root/'verificacao-exportacao.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({k:v for k,v in report.items() if k!='checked_frames'},ensure_ascii=False))
