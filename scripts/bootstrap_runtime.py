#!/usr/bin/env python3
"""Install pinned Wav2Lip code and provision the verified inference checkpoint."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from urllib.parse import urlparse
from urllib.request import urlopen
import zipfile

ROOT=Path(__file__).resolve().parents[1]
MAX_BYTES=1024**3

def digest(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for chunk in iter(lambda:f.read(1024*1024),b''):h.update(chunk)
    return h.hexdigest()

def code_root():
    return Path(os.environ.get('WAV2LIP_ROOT',str(ROOT/'.local/Wav2Lip')))

def checkpoint_path():
    return Path(os.environ.get('WAV2LIP_CHECKPOINT',str(code_root()/'checkpoints/wav2lip-compatible.pth')))

def install_code():
    target=code_root();target.parent.mkdir(parents=True,exist_ok=True)
    commit=json.loads((ROOT/'deploy/model.json').read_text())['wav2lip_commit']
    if not (target/'.git').exists():
        if target.exists() and any(target.iterdir()):raise RuntimeError('WAV2LIP_ROOT deve estar vazio ou conter o repositório fixado')
        target.mkdir(exist_ok=True)
        subprocess.run(['git','init','-q',str(target)],check=True)
        subprocess.run(['git','-C',str(target),'remote','add','origin','https://github.com/Rudrabha/Wav2Lip.git'],check=True)
        subprocess.run(['git','-C',str(target),'fetch','--depth=1','origin',commit],check=True,timeout=180)
        subprocess.run(['git','-C',str(target),'checkout','-q','--detach','FETCH_HEAD'],check=True)
    actual=subprocess.check_output(['git','-C',str(target),'rev-parse','HEAD'],text=True).strip()
    if actual!=commit:raise RuntimeError('Wav2Lip possui revisão diferente da versão validada')
    audio=target/'audio.py';s=audio.read_text().replace('librosa.filters.mel(hp.sample_rate, hp.n_fft,','librosa.filters.mel(sr=hp.sample_rate, n_fft=hp.n_fft,');audio.write_text(s)
    infer=target/'inference.py';s=infer.read_text().replace('torch.load(checkpoint_path)','torch.load(checkpoint_path, weights_only=True)').replace('map_location=lambda storage, loc: storage)',"map_location='cpu', weights_only=True)");infer.write_text(s)
    print('Código Wav2Lip instalado e fixado.',flush=True)

def verified_copy(source,destination,expected):
    source=Path(source);destination=Path(destination)
    destination.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='checkpoint-',dir=destination.parent) as tmp:
        candidate=Path(tmp)/'model.pth'
        if zipfile.is_zipfile(source):
            with zipfile.ZipFile(source) as z:
                names=[n for n in z.namelist() if Path(n).name=='wav2lip-compatible.pth']
                if len(names)!=1 or z.getinfo(names[0]).file_size>MAX_BYTES:raise RuntimeError('ZIP não contém um único checkpoint compatível válido')
                with z.open(names[0]) as src,candidate.open('wb') as dst:shutil.copyfileobj(src,dst)
        else:
            if source.stat().st_size>MAX_BYTES:raise RuntimeError('modelo excede o tamanho permitido')
            shutil.copyfile(source,candidate)
        if digest(candidate)!=expected:raise RuntimeError('SHA-256 do checkpoint não corresponde ao modelo validado')
        os.replace(candidate,destination)

def provision(source=None):
    metadata=json.loads((ROOT/'deploy/model.json').read_text())
    expected=os.environ.get('WAV2LIP_CHECKPOINT_SHA256') or metadata['sha256']
    if not expected:raise RuntimeError('defina o SHA-256 do modelo')
    dest=checkpoint_path()
    if dest.is_file() and digest(dest)==expected:
        print('Checkpoint já instalado e verificado.',flush=True);return
    if source:
        verified_copy(source,dest,expected);return
    url=os.environ.get('WAV2LIP_CHECKPOINT_URL','')
    if not url:raise RuntimeError('Configure WAV2LIP_CHECKPOINT_URL com o link do modelo/PACOTE do Drive ou monte o checkpoint validado no servidor')
    parsed=urlparse(url)
    if parsed.scheme not in ('https','http'):raise RuntimeError('URL do modelo deve usar HTTP ou HTTPS')
    dest.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='download-',dir=dest.parent) as tmp:
        downloaded=Path(tmp)/'download'
        try:
            if parsed.hostname in ('drive.google.com','drive.usercontent.google.com'):
                import gdown
                if not gdown.download(url,str(downloaded),quiet=True,fuzzy=True):raise RuntimeError('download indisponível')
            else:
                total=0
                with urlopen(url,timeout=90) as src,downloaded.open('wb') as dst:
                    while True:
                        chunk=src.read(1024*1024)
                        if not chunk:break
                        total+=len(chunk)
                        if total>MAX_BYTES:raise RuntimeError('download excede limite')
                        dst.write(chunk)
        except Exception:
            raise RuntimeError('Não foi possível baixar o modelo; confira WAV2LIP_CHECKPOINT_URL e as permissões de download') from None
        verified_copy(downloaded,dest,expected)
    print('Checkpoint baixado e verificado.',flush=True)

def check():
    for cmd in ('ffmpeg','ffprobe'):
        if not shutil.which(cmd):raise RuntimeError(cmd+' não instalado')
    browser=os.environ.get('CHROMIUM_BIN') or shutil.which('chromium') or '/opt/google/chrome/chrome'
    if not Path(browser).is_file():raise RuntimeError('Chromium não instalado; defina CHROMIUM_BIN')
    for module in ('torch','cv2','librosa','playwright.sync_api','edge_tts','fastapi','dotenv'):
        __import__(module)
    if not (code_root()/'inference.py').is_file() or not checkpoint_path().is_file():raise RuntimeError('sincronizador incompleto')
    catalog=json.loads((ROOT/'templates/vestuario/catalogo.json').read_text())
    if len(catalog['variants'])<10:raise RuntimeError('catálogo de roupas incompleto')
    for variant in catalog['variants']:
        if not (ROOT/'templates/vestuario'/variant['file']).is_file():raise RuntimeError('clipe de roupa ausente')
    print('Runtime pronto: bibliotecas, FFmpeg, navegador, roupas e modelo.',flush=True)

if __name__=='__main__':
    from dotenv import load_dotenv
    load_dotenv(ROOT/'.env',override=False)
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--code-only',action='store_true');p.add_argument('--check-only',action='store_true');p.add_argument('--checkpoint-file',type=Path)
    a=p.parse_args()
    if a.check_only:check()
    else:
        install_code()
        if not a.code_only:provision(a.checkpoint_file);check()
