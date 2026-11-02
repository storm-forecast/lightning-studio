"""Compact worldwide rain and nowcasting feed for major cities."""
import json
import time
from urllib.parse import urlencode
from urllib.request import urlopen

CITIES={
 'new-york':('New York','United States',40.7128,-74.0060),'london':('London','United Kingdom',51.5072,-0.1276),
 'paris':('Paris','France',48.8566,2.3522),'tokyo':('Tokyo','Japan',35.6762,139.6503),
 'mumbai':('Mumbai','India',19.0760,72.8777),'singapore':('Singapore','Singapore',1.3521,103.8198),
 'sydney':('Sydney','Australia',-33.8688,151.2093),'mexico-city':('Mexico City','Mexico',19.4326,-99.1332),
 'sao-paulo':('São Paulo','Brazil',-23.5505,-46.6333),'buenos-aires':('Buenos Aires','Argentina',-34.6037,-58.3816),
 'johannesburg':('Johannesburg','South Africa',-26.2041,28.0473),'cairo':('Cairo','Egypt',30.0444,31.2357),
}
_cache=(0,[])

def alerts():
    global _cache
    if time.time()-_cache[0] < 600:return _cache[1]
    rows=[]
    for ident,(city,country,lat,lon) in CITIES.items():
        query=urlencode({'latitude':lat,'longitude':lon,'current':'rain,precipitation,weather_code','hourly':'precipitation_probability,precipitation','forecast_days':1,'timezone':'auto'})
        try:
            with urlopen('https://api.open-meteo.com/v1/forecast?'+query,timeout=15) as response:data=json.load(response)
            current=data.get('current',{}); hourly=data.get('hourly',{})
            probability=max((x or 0) for x in hourly.get('precipitation_probability',[])[:6])
            rain=float(current.get('rain') or current.get('precipitation') or 0)
            level='alta' if rain>=5 or probability>=70 else 'moderada' if rain>0 or probability>=40 else 'baixa'
            rows.append({'id':ident,'cidade':city,'pais':country,'lat':lat,'lon':lon,'nivel':level,'chuva_atual_mm':rain,'probabilidade_6h':probability,'observado_em':current.get('time'),'fonte':'Open-Meteo','oficial':False})
        except Exception as exc:rows.append({'id':ident,'cidade':city,'pais':country,'erro':str(exc),'fonte':'Open-Meteo','oficial':False})
    _cache=(time.time(),rows);return rows
