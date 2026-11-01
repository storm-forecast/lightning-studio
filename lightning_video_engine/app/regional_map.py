"""Georeferenced OSM basemap shared by every city Short, with disk tile cache."""
import io
import math
import os
import time
from pathlib import Path
from urllib.request import Request, urlopen
from PIL import Image, ImageDraw, ImageFont

ATTRIBUTION = '© OpenStreetMap contributors • openstreetmap.org/copyright'


def mercator(lat):
    return math.log(math.tan(math.pi / 4 + math.radians(lat) / 2))


def basemap(bounds, cache, size=(640,600), zoom=9):
    west,east,south,north = bounds
    scale=256*2**zoom
    def pixel(lat,lon):
        return (lon+180)/360*scale,(1-mercator(lat)/math.pi)/2*scale
    left,top=pixel(north,west);right,bottom=pixel(south,east)
    x0,y0=int(left//256),int(top//256)
    x1,y1=int(right//256),int(bottom//256)
    if (x1-x0+1)*(y1-y0+1)>36:
        raise ValueError('recorte do mapa excedeu o limite de tiles')
    canvas=Image.new('RGB',((x1-x0+1)*256,(y1-y0+1)*256))
    cache=Path(cache);cache.mkdir(parents=True,exist_ok=True)
    for y in range(y0,y1+1):
        for x in range(x0,x1+1):
            path=cache/f'{zoom}-{x}-{y}.png'
            if not path.exists() or time.time()-path.stat().st_mtime>7*86400:
                request=Request(f'https://tile.openstreetmap.org/{zoom}/{x}/{y}.png',headers={
                    'User-Agent':'LightningStudio/0.1 (local weather bulletin renderer)',
                    'Accept':'image/png'})
                with urlopen(request,timeout=30) as response:data=response.read()
                Image.open(io.BytesIO(data)).verify()
                path.write_bytes(data)
            with Image.open(path) as tile:
                canvas.paste(tile.convert('RGB'),((x-x0)*256,(y-y0)*256))
    return canvas.crop((round(left-x0*256),round(top-y0*256),round(right-x0*256),round(bottom-y0*256))).resize(size,Image.Resampling.LANCZOS)
