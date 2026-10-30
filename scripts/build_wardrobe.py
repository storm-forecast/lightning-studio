#!/usr/bin/env python3
"""Prepare ten color variants of the existing white blouse, without changing motion.

This recolors the existing garment; it does not generate new cuts or outfits.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import cv2
import numpy as np

PALETTE=[('branco','Branco',None),('azul-marinho','Azul-marinho','#233f67'),
 ('petroleo','Azul-petróleo','#246775'),('esmeralda','Verde-esmeralda','#26705e'),
 ('bordo','Bordô','#803b53'),('ameixa','Ameixa','#644477'),
 ('grafite','Grafite','#505866'),('azul','Azul executivo','#365e9b'),
 ('terracota','Terracota','#9a5d4d'),('oliva','Verde-oliva','#66704a')]


_SESSION=None

def person_mask(frame):
    global _SESSION
    if _SESSION is None:
        import onnxruntime as ort
        options=ort.SessionOptions();options.intra_op_num_threads=2;options.inter_op_num_threads=1
        _SESSION=ort.InferenceSession(str(ROOT/'.local/u2netp.onnx'),sess_options=options,providers=['CPUExecutionProvider'])
    rgb=cv2.cvtColor(cv2.resize(frame,(320,320)),cv2.COLOR_BGR2RGB).astype(np.float32)/255
    rgb=(rgb-np.array([.485,.456,.406],np.float32))/np.array([.229,.224,.225],np.float32)
    tensor=np.transpose(rgb,(2,0,1))[None]
    pred=_SESSION.run(None,{_SESSION.get_inputs()[0].name:tensor})[0][0,0]
    pred=(pred-pred.min())/max(float(pred.max()-pred.min()),1e-6)
    return cv2.resize(np.clip((pred-.6)/.3,0,1),frame.shape[1::-1])


def garment_mask(frame):
    """Neutral blouse component below the face, excluding skin and background rails."""
    h,w=frame.shape[:2]
    hsv=cv2.cvtColor(frame,cv2.COLOR_BGR2HSV)
    # Blouse in the approved source is neutral; studio walls are cyan.
    neutral=((hsv[:,:,1]<55)&(hsv[:,:,2]>105)).astype(np.uint8)
    neutral[:int(h*.40)]=0
    neutral[:, :int(w*.25)]=0;neutral[:,int(w*.76):]=0
    neutral[int(h*.97):]=0
    # Isolate the connected cloth around the torso. Do not recolor disconnected rails.
    count,labels,stats,_=cv2.connectedComponentsWithStats(neutral,8)
    seed=labels[int(h*.56):int(h*.78),int(w*.45):int(w*.55)]
    ids,freq=np.unique(seed[seed>0],return_counts=True)
    if not len(ids):raise RuntimeError('não foi possível localizar a blusa branca')
    label=int(ids[np.argmax(freq)])
    mask=(labels==label).astype(np.uint8)
    # Connected background rails have a very wide, shallow shape: fail instead of tinting the set.
    if stats[label,cv2.CC_STAT_AREA]>h*w*.32:raise RuntimeError('máscara da roupa invadiu o cenário')
    mask=cv2.morphologyEx(mask,cv2.MORPH_CLOSE,np.ones((3,3),np.uint8))
    alpha=cv2.GaussianBlur(mask.astype(np.float32),(5,5),0)
    # Preserve warm skin (hands and neck), even where it borders the white cloth.
    warm=(frame[:,:,2].astype(float)-frame[:,:,0].astype(float))>22
    alpha[warm]=0
    return alpha*person_mask(frame)


def recolor(frame,alpha,color):
    bgr=np.array([int(color[i:i+2],16) for i in (5,3,1)],np.float32)
    light=cv2.cvtColor(frame,cv2.COLOR_BGR2GRAY).astype(np.float32)/220
    cloth=np.clip(light[:,:,None]*bgr[None,None,:],0,255)
    return np.uint8(np.clip(frame*(1-alpha[:,:,None])+cloth*alpha[:,:,None],0,255))


def build(source,out,preview_only=False):
    out.mkdir(parents=True,exist_ok=True)
    cap=cv2.VideoCapture(str(source));fps=cap.get(cv2.CAP_PROP_FPS)
    w,h=int(cap.get(3)),int(cap.get(4));frames=int(cap.get(7))
    cap.set(cv2.CAP_PROP_POS_MSEC,2000);ok,sample=cap.read()
    if not ok:raise RuntimeError('vídeo-base ilegível')
    mask=garment_mask(sample)
    from PIL import Image,ImageDraw,ImageFont
    sheet=Image.new('RGB',(1600,800),'#102337');draw=ImageDraw.Draw(sheet)
    font=ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',18)
    for i,(key,name,color) in enumerate(PALETTE):
        frame=recolor(sample,mask,color) if color else sample
        im=Image.fromarray(cv2.cvtColor(frame,cv2.COLOR_BGR2RGB)).crop((w//2-320,0,w//2+320,h)).resize((320,360))
        x,y=(i%5)*320,(i//5)*400
        sheet.paste(im,(x,y+35));draw.text((x+10,y+5),name,font=font,fill='white')
    sheet.save(out/'previa-vestuario.jpg')
    if preview_only:return
    cap.set(cv2.CAP_PROP_POS_FRAMES,0)
    cache=out/'.masks';cache.mkdir(exist_ok=True)
    for n in range(frames):
        ok,frame=cap.read()
        if not ok:raise RuntimeError('vídeo incompleto')
        file=cache/f'{n:04}.png'
        cv2.imwrite(str(file),np.uint8(garment_mask(frame)*255))
    print('Máscaras de roupa preparadas.',flush=True)
    # One video at a time limits memory and CPU. Original source and face are preserved.
    items=[]
    for key,name,color in PALETTE:
        file=out/f'{key}.mp4'
        cmd=['ffmpeg','-y','-v','error','-f','rawvideo','-pix_fmt','bgr24','-s',f'{w}x{h}',
             '-r',str(fps),'-i','-','-an','-c:v','libx264','-preset','veryfast','-crf','19',
             '-threads','2','-pix_fmt','yuv420p','-movflags','+faststart',str(file)]
        cap.set(cv2.CAP_PROP_POS_FRAMES,0)
        process=subprocess.Popen(cmd,stdin=subprocess.PIPE)
        n=0
        try:
            while True:
                ok,frame=cap.read()
                if not ok:break
                if color:
                    alpha=cv2.imread(str(cache/f'{n:04}.png'),cv2.IMREAD_GRAYSCALE).astype(np.float32)/255
                    frame=recolor(frame,alpha,color)
                process.stdin.write(frame.tobytes());n+=1
            process.stdin.close()
            if process.wait()!=0:raise RuntimeError('falha ao exportar '+key)
        except Exception:
            process.kill();process.wait();file.unlink(missing_ok=True);raise
        if n!=frames:raise RuntimeError('número de quadros inesperado')
        items.append({'id':key,'name':name,'color':color,'file':file.name,
                      'sha256':hashlib.sha256(file.read_bytes()).hexdigest()})
        print('Preparado:',name,flush=True)
    cap.release()
    import shutil
    shutil.rmtree(cache)
    (out/'catalogo.json').write_text(json.dumps({'version':1,'kind':'same_blouse_color_variants',
        'source_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),
        'anchor_date':'2026-01-01','timezone':'America/Belem','variants':items},ensure_ascii=False,indent=2)+'\n')

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source',type=Path,default=ROOT/'templates/apresentadora-base.mp4')
    p.add_argument('--output',type=Path,default=ROOT/'templates/vestuario')
    p.add_argument('--preview-only',action='store_true')
    a=p.parse_args();cv2.setNumThreads(1);build(a.source,a.output,a.preview_only)
