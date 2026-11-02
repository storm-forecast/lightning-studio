"""Compact worldwide rain and nowcasting feed for major cities."""
import json
import time
from urllib.parse import urlencode
from urllib.request import Request, urlopen

CITIES={
 'new-york':('New York','United States',40.7128,-74.0060),'london':('London','United Kingdom',51.5072,-0.1276),
 'paris':('Paris','France',48.8566,2.3522),'tokyo':('Tokyo','Japan',35.6762,139.6503),
 'mumbai':('Mumbai','India',19.0760,72.8777),'singapore':('Singapore','Singapore',1.3521,103.8198),
 'sydney':('Sydney','Australia',-33.8688,151.2093),'mexico-city':('Mexico City','Mexico',19.4326,-99.1332),
 'sao-paulo':('São Paulo','Brazil',-23.5505,-46.6333),'buenos-aires':('Buenos Aires','Argentina',-34.6037,-58.3816),
 'johannesburg':('Johannesburg','South Africa',-26.2041,28.0473),'cairo':('Cairo','Egypt',30.0444,31.2357),
 'ongole':('Ongole','India',15.50357,80.04454),
 'hibbing':('Hibbing, Minnesota','United States',47.42715,-92.93769),
 'international-falls':('International Falls, Minnesota','United States',48.60105,-93.41098),
 'mulvane':('Mulvane, Kansas','United States',37.47446,-97.24393),
 'toronto':('Toronto','Canada',43.6532,-79.3832),
 'montreal':('Montréal','Canada',45.5017,-73.5673),
 'vancouver':('Vancouver','Canada',49.2827,-123.1207),
}
_cache=(0,[])

def _florida_official_alerts():
    """Active NWS flood alerts, kept geographically specific rather than labelling all Florida."""
    request = Request('https://api.weather.gov/alerts/active?area=FL', headers={
        'User-Agent': 'TROVOX-GLOBAL weather nowcasting'})
    with urlopen(request, timeout=20) as response:
        features = json.load(response).get('features', [])
    rank = {'Flash Flood Warning': 0, 'Flood Warning': 1, 'Flood Advisory': 2, 'Flood Watch': 3}
    candidates = [feature for feature in features if feature.get('properties', {}).get('event') in rank]
    if not candidates:
        return []
    feature = min(candidates, key=lambda value: rank[value['properties']['event']])
    props, geometry = feature['properties'], feature.get('geometry') or {}
    points = geometry.get('coordinates', [[]])[0] if geometry.get('type') == 'Polygon' else []
    if points:
        lon = sum(point[0] for point in points) / len(points)
        lat = sum(point[1] for point in points) / len(points)
    else:
        # A state-wide watch without polygon remains a regional alert, not a fabricated pinpoint.
        lat, lon = 27.8, -81.7
    return [{'id': 'florida-flood', 'cidade': 'Affected parts of Florida', 'pais': 'United States',
             'lat': lat, 'lon': lon, 'nivel': 'alta', 'gatilhos': ['official_flood_alert'],
             'evento_oficial': props['event'], 'areas_afetadas': props.get('areaDesc', ''),
             'instrucao_oficial': props.get('instruction', ''), 'observado_em': props.get('sent'),
             'geometria_alerta': geometry,
             'timezone': 'America/New_York', 'fonte': props.get('senderName', 'National Weather Service'),
             'oficial': True}]


def _miami_official_alerts():
    """A Miami-specific official flood watch; do not reuse a warning from another county."""
    request = Request('https://api.weather.gov/alerts/active?point=25.7617,-80.1918', headers={
        'User-Agent': 'TROVOX-GLOBAL weather nowcasting'})
    with urlopen(request, timeout=20) as response:
        features = json.load(response).get('features', [])
    feature = next((value for value in features if value.get('properties', {}).get('event') == 'Flood Watch'), None)
    if feature is None:
        return []
    props = feature['properties']
    return [{'id': 'miami-flood', 'cidade': 'Miami, Florida', 'pais': 'United States',
             'lat': 25.7617, 'lon': -80.1918, 'nivel': 'alta', 'gatilhos': ['official_flood_alert'],
             'evento_oficial': props['event'], 'areas_afetadas': props.get('areaDesc', 'Miami area'),
             'instrucao_oficial': props.get('instruction', ''), 'observado_em': props.get('sent'),
             'geometria_alerta': feature.get('geometry'), 'timezone': 'America/New_York',
             'fonte': props.get('senderName', 'National Weather Service'), 'oficial': True}]


def _oklahoma_city_official_alerts():
    request = Request('https://api.weather.gov/alerts/active?point=35.4676,-97.5164', headers={
        'User-Agent': 'TROVOX-GLOBAL weather nowcasting'})
    with urlopen(request, timeout=20) as response:
        features = json.load(response).get('features', [])
    feature = next((value for value in features if value.get('properties', {}).get('event') == 'Tornado Watch'), None)
    if feature is None:
        return []
    props = feature['properties']
    return [{'id': 'oklahoma-city-severe', 'cidade': 'Oklahoma City, Oklahoma', 'pais': 'United States',
             'lat': 35.4676, 'lon': -97.5164, 'nivel': 'alta', 'gatilhos': ['official_severe_alert'],
             'evento_oficial': props['event'], 'areas_afetadas': props.get('areaDesc', 'Oklahoma City area'),
             'instrucao_oficial': props.get('instruction', ''), 'observado_em': props.get('sent'),
             'geometria_alerta': feature.get('geometry'), 'timezone': 'America/Chicago',
             'fonte': props.get('senderName', 'National Weather Service'), 'oficial': True}]

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
            flood=rain>=5 or accumulated_3h>=20 or accumulated_6h>=20
            # Strong gusts can cause local disruption before the conventional
            # severe-thunderstorm threshold. Publish a clearly-labelled
            # severe-weather-potential Short from 50 km/h upward.
            severe=code in (95,96,99) or gust>=50
            heavy_rain=probability>=80 and accumulated_6h>=15
            level='alta' if flood or severe or heavy_rain else 'moderada' if rain>0 or probability>=40 else 'baixa'
            triggers=[]
            if flood: triggers.append('potential_flooding')
            if severe: triggers.append('severe_weather')
            if heavy_rain: triggers.append('heavy_rain')
            rows.append({'id':ident,'cidade':city,'pais':country,'lat':lat,'lon':lon,'nivel':level,'gatilhos':triggers,'chuva_atual_mm':rain,'probabilidade_6h':probability,'chuva_acumulada_3h_mm':round(accumulated_3h,1),'chuva_acumulada_6h_mm':round(accumulated_6h,1),'rajada_maxima_6h_kmh':round(gust,1),'codigo_tempo':code,'observado_em':current.get('time'),'timezone':data.get('timezone','UTC'),'fonte':'Open-Meteo','oficial':False})
        except Exception as exc:rows.append({'id':ident,'cidade':city,'pais':country,'erro':str(exc),'fonte':'Open-Meteo','oficial':False})
    try:
        rows.extend(_florida_official_alerts())
    except Exception as exc:
        rows.append({'id':'florida-flood','cidade':'Affected parts of Florida','erro':str(exc),'fonte':'NWS','oficial':True})
    try:
        rows.extend(_miami_official_alerts())
    except Exception as exc:
        rows.append({'id':'miami-flood','cidade':'Miami, Florida','erro':str(exc),'fonte':'NWS','oficial':True})
    try:
        rows.extend(_oklahoma_city_official_alerts())
    except Exception as exc:
        rows.append({'id':'oklahoma-city-severe','cidade':'Oklahoma City, Oklahoma','erro':str(exc),'fonte':'NWS','oficial':True})
    _cache=(time.time(),rows);return rows
