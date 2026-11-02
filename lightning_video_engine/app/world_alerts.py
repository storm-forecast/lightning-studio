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
 'ongole':('Ongole','India',15.50357,80.04454),
}
_cache=(0,[])

def alerts():
    global _cache
    if time.time()-_cache[0] < 600:return _cache[1]
    rows=[]
    for ident,(city,country,lat,lon) in CITIES.items():
        query=urlencode({'latitude':lat,'longitude':lon,'current':'rain,precipitation,weather_code,wind_gusts_10m','hourly':'precipitation_probability,precipitation,wind_gusts_10m','forecast_days':1,'timezone':'auto'})
        try:
            with urlopen('https://api.open-meteo.com/v1/forecast?'+query,timeout=15) as response:data=json.load(response)
            current=data.get('current',{}); hourly=data.get('hourly',{})
            times=hourly.get('time',[])
            start=next((i for i,value in enumerate(times) if value >= current.get('time','')),0)
            probability=max((x or 0) for x in hourly.get('precipitation_probability',[])[start:start+6])
            accumulated_3h=sum((x or 0) for x in hourly.get('precipitation',[])[start:start+3])
            accumulated_6h=sum((x or 0) for x in hourly.get('precipitation',[])[start:start+6])
            gust=max([float(current.get('wind_gusts_10m') or 0)] + [float(x or 0) for x in hourly.get('wind_gusts_10m',[])[start:start+6]])
            rain=float(current.get('rain') or current.get('precipitation') or 0)
            code=int(current.get('weather_code') or 0)
            flood=rain>=5 or accumulated_3h>=20 or accumulated_6h>=35
            severe=code in (95,96,99) or gust>=70
            heavy_rain=probability>=80 and accumulated_6h>=15
            level='alta' if flood or severe or heavy_rain else 'moderada' if rain>0 or probability>=40 else 'baixa'
            triggers=[]
            if flood: triggers.append('potential_flooding')
            if severe: triggers.append('severe_weather')
            if heavy_rain: triggers.append('heavy_rain')
            rows.append({'id':ident,'cidade':city,'pais':country,'lat':lat,'lon':lon,'nivel':level,'gatilhos':triggers,'chuva_atual_mm':rain,'probabilidade_6h':probability,'chuva_acumulada_3h_mm':round(accumulated_3h,1),'chuva_acumulada_6h_mm':round(accumulated_6h,1),'rajada_maxima_6h_kmh':round(gust,1),'codigo_tempo':code,'observado_em':current.get('time'),'timezone':data.get('timezone','UTC'),'fonte':'Open-Meteo','oficial':False})
        except Exception as exc:rows.append({'id':ident,'cidade':city,'pais':country,'erro':str(exc),'fonte':'Open-Meteo','oficial':False})
    _cache=(time.time(),rows);return rows
