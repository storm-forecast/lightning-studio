"""Deterministic daily wardrobe rotation, pinned in each job's manifest."""
from datetime import date,datetime
from pathlib import Path
from zoneinfo import ZoneInfo
import json
import hashlib
import os

ROOT=Path(__file__).resolve().parents[2]


def wardrobe_for_day(at=None, *, catalog_path=None):
    catalog_path=Path(catalog_path or os.environ.get('PRESENTER_WARDROBE_CATALOG') or ROOT/'templates/vestuario/catalogo.json')
    catalog=json.loads(catalog_path.read_text())
    tz=ZoneInfo(os.environ.get('VIDEO_TIMEZONE',catalog.get('timezone','America/Belem')))
    at=at or datetime.now(tz)
    if at.tzinfo is None:raise ValueError('a data deve incluir fuso horário')
    day=at.astimezone(tz).date()
    variants=catalog['variants']
    if len(variants)<10:raise ValueError('o catálogo diário deve ter pelo menos 10 variações')
    index=(day-date.fromisoformat(catalog['anchor_date'])).days%len(variants)
    item=variants[index]
    file=(catalog_path.parent/item['file']).resolve()
    if not file.is_file():raise FileNotFoundError(file)
    if hashlib.sha256(file.read_bytes()).hexdigest()!=item['sha256']:
        raise ValueError('arquivo de vestuário diferente do catálogo; prepare-o novamente')
    return {'date':day.isoformat(),'timezone':str(tz),'id':item['id'],
            'name':item['name'],'file':str(file),'sha256':item['sha256']}


def wardrobe_for_job(directory, at=None):
    manifest=Path(directory)/'vestuario.json'
    if manifest.exists():
        selected=json.loads(manifest.read_text())
        file=Path(selected['file'])
        if not file.is_file():raise FileNotFoundError(file)
        if hashlib.sha256(file.read_bytes()).hexdigest()!=selected['sha256']:
            raise ValueError('a roupa registrada no job foi alterada')
        return selected
    selected=wardrobe_for_day(at)
    manifest.parent.mkdir(parents=True,exist_ok=True)
    manifest.write_text(json.dumps(selected,ensure_ascii=False,indent=2)+'\n')
    return selected
