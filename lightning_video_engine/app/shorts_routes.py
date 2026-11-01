"""Protected city nowcasting videos; generation never publishes automatically."""
import hmac
import os
import re

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import FileResponse

router = APIRouter(prefix='/v1/shorts', tags=['shorts nowcasting'])


def monitor(request: Request, x_video_token: str = Header('')):
    expected = os.environ.get('VIDEO_ENGINE_TOKEN', '')
    if not expected or not hmac.compare_digest(expected, x_video_token):
        raise HTTPException(401, 'token de vídeo inválido')
    service = getattr(request.app.state, 'city_shorts', None)
    if service is None:
        raise HTTPException(503, 'monitor de vídeos indisponível')
    return service


@router.get('/cidades')
def cities(service=Depends(monitor)):
    from .city_shorts import CITIES
    return {'cidades': [{'id': k, 'nome': v[0], 'uf': v[1], 'lat': v[2], 'lon': v[3], 'raio_km': 40}
                        for k, v in CITIES.items()], 'automatico': os.environ.get('SHORTS_MONITOR_ENABLED', '').lower() == 'true'}


@router.post('/verificar')
def check(service=Depends(monitor)):
    return service.check()


@router.get('/{video_id}')
def status(video_id: str, service=Depends(monitor)):
    item = service.get(video_id)
    if item is None:
        raise HTTPException(404, 'vídeo não encontrado')
    return item


@router.get('/{video_id}/video')
def download(video_id: str, service=Depends(monitor)):
    if not re.fullmatch('[a-f0-9]{32}', video_id):
        raise HTTPException(404, 'vídeo não encontrado')
    item = service.get(video_id)
    if not item or item['estado'] != 'concluido':
        raise HTTPException(404, 'vídeo ainda não disponível')
    return FileResponse(service.root / video_id / 'short.mp4', media_type='video/mp4')
