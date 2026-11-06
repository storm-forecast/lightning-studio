"""Compact worldwide rain and nowcasting feed for major cities."""
import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
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
 # Critical US cities: tornado and hurricane corridors and storm-prone metros.
 'miami':('Miami, Florida','United States',25.7617,-80.1918),
 'tampa':('Tampa, Florida','United States',27.9506,-82.4572),
 'jacksonville':('Jacksonville, Florida','United States',30.3322,-81.6557),
 'new-orleans':('New Orleans, Louisiana','United States',29.9511,-90.0715),
 'houston':('Houston, Texas','United States',29.7604,-95.3698),
 'dallas':('Dallas, Texas','United States',32.7767,-96.7970),
 'san-antonio':('San Antonio, Texas','United States',29.4241,-98.4936),
 'austin':('Austin, Texas','United States',30.2672,-97.7431),
 'oklahoma-city':('Oklahoma City, Oklahoma','United States',35.4676,-97.5164),
 'kansas-city':('Kansas City, Missouri','United States',39.0997,-94.5786),
 'st-louis':('St. Louis, Missouri','United States',38.6270,-90.1994),
 'memphis':('Memphis, Tennessee','United States',35.1495,-90.0490),
 'nashville':('Nashville, Tennessee','United States',36.1627,-86.7816),
 'atlanta':('Atlanta, Georgia','United States',33.7490,-84.3880),
 'charlotte':('Charlotte, North Carolina','United States',35.2271,-80.8431),
 'chicago':('Chicago, Illinois','United States',41.8781,-87.6298),
 'minneapolis':('Minneapolis, Minnesota','United States',44.9778,-93.2650),
 'denver':('Denver, Colorado','United States',39.7392,-104.9903),
}
_cache=(0,[])
_cache_lock=threading.Lock()
NWS_HEADERS={'User-Agent':'TROVOX-GLOBAL weather nowcasting'}
# NWS events that describe storms, flooding or tropical systems, most urgent first.
NWS_WARNINGS=('Tornado Warning','Extreme Wind Warning','Hurricane Warning','Storm Surge Warning','Flash Flood Warning',
              'Severe Thunderstorm Warning','Tropical Storm Warning','Flood Warning')
NWS_WATCHES=('Tornado Watch','Hurricane Watch','Severe Thunderstorm Watch','Storm Surge Watch','Tropical Storm Watch',
             'Flash Flood Watch','Flood Watch')
NWS_RANK={event:rank for rank,event in enumerate(NWS_WARNINGS+NWS_WATCHES)}
# Forecasts change hourly; a shared cache keeps five-minute passes inside Open-Meteo's free daily limit.
FORECAST_TTL=1200


def _nws_trigger(event):
    return 'official_warning' if event in NWS_WARNINGS else 'official_watch' if event in NWS_WATCHES else 'official_flood_alert'


def _florida_official_alerts():
    """Active NWS flood alerts, kept geographically specific rather than labelling all Florida."""
    request = Request('https://api.weather.gov/alerts/active?area=FL', headers=NWS_HEADERS)
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
             'lat': lat, 'lon': lon, 'nivel': 'alta', 'gatilhos': [_nws_trigger(props['event'])],
             'evento_oficial': props['event'], 'alerta_id': props.get('id'), 'areas_afetadas': props.get('areaDesc', ''),
             'instrucao_oficial': props.get('instruction', ''), 'observado_em': props.get('sent'),
             'geometria_alerta': geometry,
             'timezone': 'America/New_York', 'fonte': props.get('senderName', 'National Weather Service'),
             'oficial': True}]


def _nws_point_alert(lat, lon):
    """The most urgent active NWS storm, flood or tropical alert covering the city centre."""
    request = Request(f'https://api.weather.gov/alerts/active?point={lat:.4f},{lon:.4f}', headers=NWS_HEADERS)
    with urlopen(request, timeout=20) as response:
        features = [value for value in json.load(response).get('features', [])
                    if value.get('properties', {}).get('event') in NWS_RANK]
    return min(features, key=lambda value: NWS_RANK[value['properties']['event']]) if features else None


def _lightning_triggers(lat, lon):
    """Observed satellite lightning over the city or a storm moving towards it; nothing is inferred."""
    base = os.environ.get('LIGHTNING_API_URL', 'https://lightning-agent.onrender.com').rstrip('/')
    with urlopen(base + '/alertas/situacao?' + urlencode({'lat': lat, 'lon': lon}), timeout=30) as response:
        value = json.load(response)
    if value.get('dados_atrasados') or value.get('janela_incompleta') or not value.get('coberto'):
        return [], value
    triggers = []
    near, trend = value.get('mais_proximo') or {}, value.get('tendencia') or {}
    if near.get('km', float('inf')) <= 15 and 0 <= near.get('minutos_atras', float('inf')) <= 15:
        triggers.append('storm_overhead')
    arrival = trend.get('minutos_ate_15km')
    if (trend.get('sentido') == 'aproximando' and trend.get('km_agora', float('inf')) <= 60 and
            isinstance(arrival, (int, float)) and arrival <= 60 and 'storm_overhead' not in triggers):
        triggers.append('storm_approaching')
    return triggers, value


def _lightning_observed(lat, lon):
    """Fresh strikes within 40 km; no reading counts as none, so a forecast alone never alerts."""
    try:
        _, value = _lightning_triggers(lat, lon)
        near = (value or {}).get('mais_proximo') or {}
    except Exception:
        return False
    fresh = value.get('coberto') and not value.get('dados_atrasados')
    return bool(fresh and near.get('km', float('inf')) <= 40 and 0 <= near.get('minutos_atras', float('inf')) <= 30)


def _forecast(ident, lat, lon):
    """Open-Meteo forecast for a city, shared across passes for FORECAST_TTL seconds."""
    path = Path(os.environ['WORLD_ALERTS_CACHE']) if os.environ.get('WORLD_ALERTS_CACHE') else None
    try:
        stored = json.loads(path.read_text()) if path else {}
    except (OSError, ValueError):
        stored = {}
    if ident in stored and time.time() - stored[ident][0] < FORECAST_TTL:
        return stored[ident][1]
    query=urlencode({'latitude':lat,'longitude':lon,'current':'rain,precipitation,weather_code,wind_gusts_10m','hourly':'precipitation_probability,precipitation,wind_gusts_10m','forecast_days':1,'timezone':'auto'})
    with urlopen('https://api.open-meteo.com/v1/forecast?'+query,timeout=15) as response:data=json.load(response)
    if path:
        with _cache_lock:
            try:
                stored = json.loads(path.read_text()) if path.exists() else {}
            except (OSError, ValueError):
                stored = {}
            stored[ident] = [time.time(), data]
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(stored))
    return data


def _city(ident, city, country, lat, lon):
    try:
        data=_forecast(ident,lat,lon)
        current=data.get('current',{}); hourly=data.get('hourly',{})
        times=hourly.get('time',[])
        start=next((i for i,value in enumerate(times) if value >= current.get('time','')),0)
        probability=max((x or 0) for x in hourly.get('precipitation_probability',[])[start:start+6])
        accumulated_3h=sum((x or 0) for x in hourly.get('precipitation',[])[start:start+3])
        accumulated_6h=sum((x or 0) for x in hourly.get('precipitation',[])[start:start+6])
        gust=max([float(current.get('wind_gusts_10m') or 0)] + [float(x or 0) for x in hourly.get('wind_gusts_10m',[])[start:start+6]])
        rain=float(current.get('rain') or current.get('precipitation') or 0)
        code=int(current.get('weather_code') or 0)
        flood=rain>=5 or accumulated_3h>=30 or accumulated_6h>=50
        # A public alert needs a dangerous signal: storm-force gusts, or a
        # thunderstorm code the same forecast also supports with likely rain.
        # A 50 km/h gust with a 0% rain chance once produced a London "alert".
        # A thunderstorm code alone is only a forecast: it needs lightning actually observed near the city.
        # A code with 0 strikes in 40 km once published a "severe weather" Short for Sao Paulo.
        storm_code=code in (95,96,99) and probability>=60
        severe=gust>=90 or (storm_code and _lightning_observed(lat,lon))
        heavy_rain=probability>=80 and accumulated_6h>=15
        level='alta' if flood or severe or heavy_rain else 'moderada' if rain>0 or probability>=40 else 'baixa'
        triggers=[]
        if flood: triggers.append('potential_flooding')
        if severe: triggers.append('severe_weather')
        if heavy_rain: triggers.append('heavy_rain')
        row={'id':ident,'cidade':city,'pais':country,'lat':lat,'lon':lon,'nivel':level,'gatilhos':triggers,'chuva_atual_mm':rain,'probabilidade_6h':probability,'chuva_acumulada_3h_mm':round(accumulated_3h,1),'chuva_acumulada_6h_mm':round(accumulated_6h,1),'rajada_maxima_6h_kmh':round(gust,1),'codigo_tempo':code,'observado_em':current.get('time'),'timezone':data.get('timezone','UTC'),'fonte':'Open-Meteo','oficial':False}
    except Exception as exc:
        if country != 'United States':
            return {'id':ident,'cidade':city,'pais':country,'erro':str(exc),'fonte':'Open-Meteo','oficial':False}
        # Official alerts and observed lightning still apply without the forecast.
        row={'id':ident,'cidade':city,'pais':country,'lat':lat,'lon':lon,'nivel':'baixa','gatilhos':[],'erro_previsao':str(exc),'fonte':'Open-Meteo','oficial':False}
    if country != 'United States':
        return row
    try:
        feature=_nws_point_alert(lat,lon)
    except Exception as exc:
        row['erro_nws']=str(exc); feature=None
    if feature:
        props=feature['properties']
        row.update(nivel='alta',evento_oficial=props['event'],alerta_id=props.get('id'),
                   areas_afetadas=props.get('areaDesc',''),instrucao_oficial=props.get('instruction',''),
                   geometria_alerta=feature.get('geometry'),fonte=props.get('senderName','National Weather Service'),oficial=True)
        row['gatilhos'].append(_nws_trigger(props['event']))
    try:
        triggers,lightning=_lightning_triggers(lat,lon)
    except Exception as exc:
        row['erro_raios']=str(exc); triggers,lightning=[],None
    if triggers:
        row['nivel']='alta'; row['gatilhos'].extend(triggers)
    row['raios_situacao']=lightning
    return row


def alerts():
    global _cache
    if time.time()-_cache[0] < 300:return _cache[1]
    with ThreadPoolExecutor(8, thread_name_prefix='world-alerts') as pool:
        rows=list(pool.map(lambda item:_city(item[0],*item[1]),CITIES.items()))
    try:
        # The state-wide alert is redundant when a monitored city already carries it.
        published={row.get('alerta_id') for row in rows if row.get('alerta_id')}
        rows.extend(row for row in _florida_official_alerts() if row.get('alerta_id') not in published)
    except Exception as exc:
        rows.append({'id':'florida-flood','cidade':'Affected parts of Florida','erro':str(exc),'fonte':'NWS','oficial':True})
    _cache=(time.time(),rows);return rows
