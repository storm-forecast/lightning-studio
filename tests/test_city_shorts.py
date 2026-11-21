from datetime import datetime, timezone, timedelta
from unittest.mock import patch

import numpy as np
import pytest

from lightning_video_engine.app import shorts_rain
from lightning_video_engine.app.city_shorts import CITIES, Monitor, evaluate


@pytest.fixture(autouse=True)
def no_area_radar_by_default():
    """No test reads the real radar; those about the area reading set their own."""
    with patch('lightning_video_engine.app.city_shorts.rain_area', return_value=None):
        yield


class CloseLightning:
    """Twelve strikes within 15 km, the last one 3 minutes ago."""
    def json(self, path, **query):
        if path == '/alertas/situacao':
            return {'dados_atrasados': False, 'coberto': True, 'raios_15km': 12, 'raios_40km': 40,
                    'mais_proximo': {'km': 6, 'minutos_atras': 3, 'direcao': 'sudoeste'}}
        return {'agora': None}


def lightning_report(*, centre=None, area=None, key='belo-horizonte'):
    with patch('lightning_video_engine.app.city_shorts.rain_at', return_value=centre), \
         patch('lightning_video_engine.app.city_shorts.rain_duration', return_value=0), \
         patch('lightning_video_engine.app.city_shorts.rain_approach', return_value=None), \
         patch('lightning_video_engine.app.city_shorts.rain_area', return_value=area):
        return evaluate(key, CloseLightning())


def radar_now(**fields):
    return dict({'coberto': True, 'hora': datetime.now(timezone.utc).timestamp()}, **fields)


def test_close_lightning_alerts_with_rain_at_the_centre():
    report = lightning_report(centre=radar_now(classe=0, nome='fraca', neve=False),
                              area=radar_now(chuva=True, km=0.0))
    assert report['gerar']
    assert any('atividade elétrica intensa' in reason for reason in report['motivos'])
    assert 'Sem confirmação de chuva' not in report['roteiro']


def test_close_lightning_alerts_with_rain_only_within_15_km():
    report = lightning_report(centre=radar_now(classe=None, nome=None, neve=False),
                              area=radar_now(chuva=True, km=9.0))
    assert report['gerar']
    assert 'Sem confirmação de chuva' not in report['roteiro']


def test_close_lightning_stays_silent_when_radar_sees_no_rain_within_15_km():
    report = lightning_report(centre=radar_now(classe=None, nome=None, neve=False),
                              area=radar_now(chuva=False, km=None))
    assert not report['gerar']
    assert report['motivos'] == []


@pytest.mark.parametrize('area', [
    None,                                                            # frame could not be read
    {'coberto': False, 'chuva': False, 'km': None, 'hora': datetime.now(timezone.utc).timestamp()},  # no radar here
    {'coberto': True, 'chuva': False, 'km': None,
     'hora': (datetime.now(timezone.utc) - timedelta(minutes=20)).timestamp()},                      # old frame
])
def test_close_lightning_alerts_and_says_so_when_radar_cannot_answer(area):
    report = lightning_report(area=area)
    assert report['gerar']
    assert 'Sem confirmação de chuva pelo radar nesta área.' in report['roteiro']


def test_spanish_alert_carries_the_missing_radar_notice():
    report = lightning_report(area=None, key='cordoba')
    assert report['gerar']
    assert 'Sin confirmación de lluvia por radar en esta zona.' in report['roteiro']


def test_density_rise_also_needs_rain_within_15_km(tmp_path):
    now = datetime.now(timezone.utc).replace(microsecond=0)
    class Rising:
        observed, count = now - timedelta(minutes=10), 2
        def json(self, path, **query):
            if path == '/alertas/situacao':
                return {'coberto': True, 'dados_atrasados': False, 'janela_incompleta': False,
                        'dados_ate': self.observed.isoformat(), 'raios_15km': self.count, 'raios_40km': self.count,
                        'mais_proximo': {'km': 9, 'minutos_atras': 2, 'direcao': 'oeste'}}
            return {'agora': None}
    source = Rising()
    monitor = Monitor(source, tmp_path)
    with patch('lightning_video_engine.app.city_shorts.rain_at', return_value=None), \
         patch('lightning_video_engine.app.city_shorts.rain_approach', return_value=None), \
         patch('lightning_video_engine.app.city_shorts.rain_area', return_value=radar_now(chuva=False, km=None)):
        monitor.evaluate_city('curitiba')
        source.observed, source.count = now, 12
        report = monitor.evaluate_city('curitiba')
    assert not report['gerar']
    assert report['densidade'] is None


def test_rain_rules_do_not_depend_on_the_area_reading():
    centre = radar_now(classe=2, nome='forte', neve=False)
    with patch('lightning_video_engine.app.city_shorts.rain_at', return_value=centre), \
         patch('lightning_video_engine.app.city_shorts.rain_duration', return_value=10), \
         patch('lightning_video_engine.app.city_shorts.rain_approach', return_value=None), \
         patch('lightning_video_engine.app.city_shorts.rain_area') as area:
        report = evaluate('belo-horizonte', Source())
    assert report['gerar']
    area.assert_not_called()


def _tile_painting(colour, offset_px, cx, cy):
    tile = np.zeros((shorts_rain.TILE_SIZE, shorts_rain.TILE_SIZE, 4), np.uint8)
    tile[cy, min(cx + offset_px, shorts_rain.TILE_SIZE - 1)] = colour
    return tile


@pytest.mark.parametrize('colour,offset_km,expected', [
    ((0x88, 0xdd, 0xee, 255), 9, True),      # the radar's weakest rain, inside the radius
    ((0x88, 0xdd, 0xee, 255), 40, False),    # same rain, outside the radius
    ((0x20, 0x20, 0x20, 255), 9, False),     # painted, but not a precipitation colour
])
def test_rain_near_reads_the_area_and_not_the_centre_pixel(colour, offset_km, expected):
    lat, lon = -19.9167, -43.9345
    tx, ty, px, py = shorts_rain._pixel_raw(lat, lon)
    km_per_px = 40075.017 * np.cos(np.radians(lat)) / (shorts_rain.TILE_SIZE * 2 ** shorts_rain.ZOOM)
    centre_tile = (tx, ty)
    offset = int(offset_km / km_per_px)
    painted = _tile_painting(colour, offset, px, py)
    blank = np.zeros_like(painted)
    blank[0, 0] = (0x20, 0x20, 0x20, 255)
    frames = [{'time': 1000, 'path': '/p'}]
    with patch.object(shorts_rain, '_get_index', return_value={'host': 'https://example.test'}), \
         patch.object(shorts_rain, '_fresh_past', return_value=frames), \
         patch.object(shorts_rain, '_tile', side_effect=lambda h, p, x, y: painted if (x, y) == centre_tile else blank):
        result = shorts_rain.rain_near(lat, lon)
    assert result['coberto'] is True
    assert result['chuva'] is expected
    assert result['hora'] == 1000
    if expected:
        assert abs(result['km'] - offset_km) < 1.5


def test_rain_near_never_calls_an_unreadable_frame_dry():
    frames = [{'time': 1000, 'path': '/p'}]
    with patch.object(shorts_rain, '_get_index', return_value={'host': 'https://example.test'}), \
         patch.object(shorts_rain, '_fresh_past', return_value=frames), \
         patch.object(shorts_rain, '_tile', return_value=None):
        assert shorts_rain.rain_near(-19.9167, -43.9345) is None


class Source:
    stale = False
    count = 0
    risk = 'baixa'
    def json(self, path, **query):
        if path == '/alertas/situacao':
            return {'dados_atrasados': self.stale, 'coberto': True, 'raios_40km': self.count,
                    'tendencia': {'sentido': 'aproximando'} if self.count else None,
                    'mais_proximo': {'km': 12, 'minutos_atras': 4, 'direcao': 'oeste'} if self.count else None}
        return {'agora': {'risco': self.risk, 'nuvens_de': '2026-11-01T12:00:00Z'}}


def test_allowlist():
    assert len(CITIES) == 57
    assert {'sao-paulo','curitiba','porto-alegre','novo-horizonte'} <= CITIES.keys()


def test_triggers_and_staleness():
    source=Source()
    radar={'coberto':True,'neve':False,'classe':0,'hora':datetime(2026,11,1,11,55,tzinfo=timezone.utc).timestamp()}
    with patch('lightning_video_engine.app.city_shorts.rain_approach', return_value=None), patch('lightning_video_engine.app.city_shorts.rain_at', return_value=radar), patch('lightning_video_engine.app.city_shorts.utc_now', return_value=datetime(2026,11,1,12)):
        assert not evaluate('curitiba',source)['gerar']
        source.count=3
        assert evaluate('curitiba',source)['gerar']
        source.stale=True
        assert not evaluate('curitiba',source)['gerar']
        source.stale=False
        radar['hora']-=1800
        assert not evaluate('curitiba',source)['gerar']


def test_radar_rain_and_recent_lightning_trigger_even_when_stationary():
    source=Source()
    source.count=3
    source.risk='alta'
    def close_lightning(path, **query):
        if path == '/alertas/situacao':
            return {'dados_atrasados':False,'coberto':True,'raios_40km':3,
                    'tendencia':{'sentido':'parada'},'mais_proximo':{'km':9,'minutos_atras':3,'direcao':'oeste'}}
        return {'agora':{'risco':'alta','nuvens_de':'2026-11-01T12:00:00Z'}}
    source.json=close_lightning
    radar={'coberto':True,'neve':False,'classe':0,'hora':datetime(2026,11,1,11,55,tzinfo=timezone.utc).timestamp()}
    with patch('lightning_video_engine.app.city_shorts.rain_approach', return_value=None), patch('lightning_video_engine.app.city_shorts.rain_at', return_value=radar), patch('lightning_video_engine.app.city_shorts.utc_now', return_value=datetime(2026,11,1,12)):
        report=evaluate('curitiba',source)
        assert report['gerar']
        assert 'chuva detectada no radar' in report['roteiro']
        assert 'se aproximando' not in report['roteiro']
        radar['classe']=None
        assert not evaluate('curitiba',source)['gerar']


def test_yellow_radar_requires_persistence_and_freshness():
    source=Source()
    radar={'coberto':True,'neve':False,'classe':2,'hora':datetime(2026,11,1,11,55,tzinfo=timezone.utc).timestamp()}
    with patch('lightning_video_engine.app.city_shorts.rain_approach', return_value=None), \
         patch('lightning_video_engine.app.city_shorts.rain_at', return_value=radar), \
         patch('lightning_video_engine.app.city_shorts.rain_duration', return_value=0) as duration, \
         patch('lightning_video_engine.app.city_shorts.utc_now', return_value=datetime(2026,11,1,12)):
        assert not evaluate('curitiba',source)['gerar']
        duration.return_value=10
        assert evaluate('curitiba',source)['gerar']
        radar['hora']-=1800
        assert not evaluate('curitiba',source)['gerar']


def persistent_rain_report(key, classe, source=None, coberto=True):
    radar={'coberto':coberto,'neve':False,'classe':classe,'hora':datetime(2026,11,1,11,55,tzinfo=timezone.utc).timestamp()}
    with patch('lightning_video_engine.app.city_shorts.rain_approach', return_value=None), \
         patch('lightning_video_engine.app.city_shorts.rain_at', return_value=radar), \
         patch('lightning_video_engine.app.city_shorts.rain_duration', return_value=60) as duration, \
         patch('lightning_video_engine.app.city_shorts.utc_now', return_value=datetime(2026,11,1,12)):
        return evaluate(key,source or Source()), duration


@pytest.mark.parametrize('key', CITIES)
def test_blue_rain_never_alerts_however_long_it_lasts(key):
    report, duration = persistent_rain_report(key, 1)
    assert not report['gerar'] and report['motivos'] == []
    duration.assert_not_called()


@pytest.mark.parametrize('key', CITIES)
def test_yellow_rain_alerts_and_measures_yellow_persistence(key):
    report, duration = persistent_rain_report(key, 2)
    assert report['gerar'] and 'moderada' not in report['roteiro']
    assert duration.call_args.args[2] == 2


@pytest.mark.parametrize('key', CITIES)
def test_persistent_rain_rule_stays_silent_without_radar_coverage(key):
    report, duration = persistent_rain_report(key, 2, coberto=False)
    assert not report['gerar'] and report['motivos'] == []
    duration.assert_not_called()


def test_lightning_still_alerts_on_blue_rain():
    source = Source()
    source.count = 3
    report, _ = persistent_rain_report('sao-paulo', 1, source)
    assert report['gerar']
    assert any('raios recentes' in reason for reason in report['motivos'])


def test_intense_close_lightning_triggers_without_radar():
    class IntenseLightning:
        def json(self,path,**query):
            if path == '/alertas/situacao':
                return {'dados_atrasados':False,'coberto':True,'raios_15km':24,'raios_40km':100,
                        'mais_proximo':{'km':8,'minutos_atras':4,'direcao':'nordeste'}}
            return {'agora':None}
    with patch('lightning_video_engine.app.city_shorts.rain_at', return_value=None), \
         patch('lightning_video_engine.app.city_shorts.rain_approach', return_value=None):
        report=evaluate('curitiba',IntenseLightning())
    assert report['gerar']
    assert any('atividade elétrica intensa' in reason for reason in report['motivos'])


def test_yellow_persistence_rejects_missing_radar_frames():
    from lightning_video_engine.app import shorts_rain
    import numpy as np
    frames=[{'time':0,'path':'older'},{'time':1200,'path':'latest'}]
    with patch.object(shorts_rain,'_get_index',return_value={'host':'https://example.test'}), \
         patch.object(shorts_rain,'_fresh_past',return_value=frames), \
         patch.object(shorts_rain,'_pixel',return_value=(0,0,0,0)), \
         patch.object(shorts_rain,'_tile',return_value=np.zeros((1,1,4))), \
         patch.object(shorts_rain,'_classe',return_value=(2,False)):
        assert shorts_rain.rain_minutes_at(-20,-44)==0


def test_lightning_density_rise_requires_two_complete_fresh_samples(tmp_path):
    now=datetime.now(timezone.utc).replace(microsecond=0)
    class LightningSource:
        observed=now-timedelta(minutes=10)
        count=2
        incomplete=False
        def json(self,path,**query):
            if path=='/alertas/situacao':
                return {'coberto':True,'dados_atrasados':False,'janela_incompleta':self.incomplete,
                        'dados_ate':self.observed.isoformat(),'raios_15km':self.count,'raios_40km':self.count,
                        'mais_proximo':{'km':9,'minutos_atras':2,'direcao':'oeste'}}
            return {'agora':None}
    source=LightningSource()
    monitor=Monitor(source,tmp_path)
    with patch('lightning_video_engine.app.city_shorts.rain_at',return_value=None), \
         patch('lightning_video_engine.app.city_shorts.rain_approach',return_value=None):
        assert not monitor.evaluate_city('curitiba')['gerar']
        source.observed=now
        source.count=9
        assert not monitor.evaluate_city('curitiba')['gerar']
        source.count=12
        report=monitor.evaluate_city('curitiba')
        assert report['gerar']
        assert report['densidade']['antes_15km']==2
        assert report['densidade']['agora_15km']==12
        # 12 strikes within 15 km also trip the intense-lightning rule, whose text comes first.
        assert any('atividade elétrica intensa' in reason for reason in report['motivos'])
        source.incomplete=True
        assert monitor.evaluate_city('curitiba')['densidade'] is None


def test_density_sample_survives_monitor_restart(tmp_path):
    now=datetime.now(timezone.utc).replace(microsecond=0)
    class SourceWithLightning:
        count=1
        observed=now-timedelta(minutes=10)
        def json(self,path,**query):
            if path=='/alertas/situacao':
                return {'coberto':True,'dados_atrasados':False,'janela_incompleta':False,
                        'dados_ate':self.observed.isoformat(),'raios_15km':self.count,'raios_40km':self.count,
                        'mais_proximo':{'km':7,'minutos_atras':1,'direcao':'oeste'}}
            return {'agora':None}
    source=SourceWithLightning()
    with patch('lightning_video_engine.app.city_shorts.rain_at',return_value=None), \
         patch('lightning_video_engine.app.city_shorts.rain_approach',return_value=None):
        Monitor(source,tmp_path).evaluate_city('curitiba')
        source.observed=now
        source.count=12
        assert Monitor(source,tmp_path).evaluate_city('curitiba')['gerar']


def test_density_trigger_survives_optional_radar_and_nowcasting_outages(tmp_path):
    now=datetime.now(timezone.utc).replace(microsecond=0)
    class LightningOnly:
        count=1
        observed=now-timedelta(minutes=10)
        def json(self,path,**query):
            if path!='/alertas/situacao':
                raise OSError('nowcasting unavailable')
            return {'coberto':True,'dados_atrasados':False,'janela_incompleta':False,
                    'dados_ate':self.observed.isoformat(),'raios_15km':self.count,
                    'raios_40km':self.count,
                    'mais_proximo':{'km':7,'minutos_atras':1,'direcao':'oeste'}}
    source=LightningOnly()
    with patch('lightning_video_engine.app.city_shorts.rain_at',side_effect=OSError('radar unavailable')), \
         patch('lightning_video_engine.app.city_shorts.rain_approach',side_effect=OSError('radar unavailable')):
        assert not Monitor(source,tmp_path).evaluate_city('curitiba')['gerar']
        source.observed=now
        source.count=12
        report=Monitor(source,tmp_path).evaluate_city('curitiba')
    assert report['gerar']
    assert report['densidade']['agora_15km']==12
    assert report['chuva'] is None
    assert report['nowcasting'] is None


def test_density_rise_rejects_reference_older_than_thirty_minutes(tmp_path):
    now=datetime.now(timezone.utc).replace(microsecond=0)
    source=Source()
    source.count=12
    source.json=lambda path,**query: (
        {'coberto':True,'dados_atrasados':False,'janela_incompleta':False,
         'dados_ate':now.isoformat(),'raios_15km':12,'raios_40km':12,
         'mais_proximo':{'km':5,'minutos_atras':1,'direcao':'oeste'}}
        if path=='/alertas/situacao' else {'agora':None})
    monitor=Monitor(source,tmp_path)
    with monitor.db() as db:
        db.execute('INSERT INTO lightning_samples VALUES (?,?,?)',
                   ('curitiba',(now-timedelta(minutes=40)).timestamp(),1))
    with patch('lightning_video_engine.app.city_shorts.rain_at',return_value=None), \
         patch('lightning_video_engine.app.city_shorts.rain_approach',return_value=None):
        # The alert may still come from the intense-lightning rule; the old sample must not make a rise.
        assert monitor.evaluate_city('curitiba')['densidade'] is None


def test_confirmed_scan_survives_changed_second_read(tmp_path):
    monitor=Monitor(None,tmp_path)
    captured={'cidade':'belo-horizonte','gerar':True,
              'verificado_em':datetime.now(timezone.utc).isoformat()}
    with patch('threading.Thread.start'), patch('lightning_video_engine.app.city_shorts.evaluate',
            side_effect=AssertionError('a second read must not replace the confirmed alert')) as reread:
        ident=monitor.check(reports={'belo-horizonte':captured})['resultados'][0]['video_id']
        with patch('lightning_video_engine.app.city_shorts.render'):
            monitor.work(monitor.get(ident),recheck=False)
    reread.assert_not_called()
    assert monitor.get(ident)['estado']=='concluido'


def test_expired_scan_is_never_dispatched(tmp_path):
    monitor=Monitor(None,tmp_path)
    captured={'cidade':'belo-horizonte','gerar':True,
              'verificado_em':(datetime.now(timezone.utc)-timedelta(minutes=16)).isoformat()}
    result=monitor.check(reports={'belo-horizonte':captured})['resultados'][0]
    assert 'expirado' in result['erro']
    assert 'video_id' not in result


def test_portuguese_script_invites_subscription_and_alerts():
    source=Source();source.count=3
    radar={'coberto':True,'neve':False,'classe':0,'hora':datetime(2026,11,1,11,55,tzinfo=timezone.utc).timestamp()}
    with patch('lightning_video_engine.app.city_shorts.rain_approach', return_value=None), patch('lightning_video_engine.app.city_shorts.rain_at', return_value=radar), patch('lightning_video_engine.app.city_shorts.utc_now', return_value=datetime(2026,11,1,12)):
        script=evaluate('curitiba',source)['roteiro']
    assert script.startswith('3 raios em 30 minutos a até 40 quilômetros de Curitiba!')
    assert 'Conte nos comentários' in script
    assert 'inscreva-se no TROVOX TEMPO para receber o próximo alerta' in script
    assert 'não confirma alagamento' not in script


def test_hook_needs_a_current_count():
    from lightning_video_engine.app.city_shorts import lightning_hook
    assert lightning_hook({'raios_40km': 12, 'dados_atrasados': False}) == 12
    assert lightning_hook({'raios_40km': 12, 'dados_atrasados': True}) is None
    assert lightning_hook({'raios_40km': 0}) is None
    assert lightning_hook({'raios_40km': None}) is None
    assert lightning_hook(None) is None


def test_dedupe_restart(tmp_path):
    monitor=Monitor(None,tmp_path)
    with patch('lightning_video_engine.app.city_shorts.CITIES', {'curitiba':('Curitiba','PR',-25,-49)}), patch('lightning_video_engine.app.city_shorts.MONITORED', ['curitiba']), patch.object(monitor,'evaluate_city', return_value={'cidade':'curitiba','gerar':True}), patch('threading.Thread.start'):
        first=monitor.check()['resultados'][0]['video_id']
        assert monitor.check()['resultados'][0]['suprimido']
    assert Monitor(None,tmp_path).get(first)['estado']=='falhou'


def test_daily_limit_survives_new_monitor(tmp_path):
    monitor=Monitor(None,tmp_path)
    with patch('lightning_video_engine.app.city_shorts.CITIES', {'curitiba':('Curitiba','PR',-25,-49)}), patch('lightning_video_engine.app.city_shorts.MONITORED', ['curitiba']), patch.object(monitor,'evaluate_city', return_value={'cidade':'curitiba','gerar':True}), patch('threading.Thread.start'):
        first=monitor.check()['resultados'][0]['video_id']
        item=monitor.get(first);item['estado']='concluido';monitor.save(item)
        assert 'suprimido' in monitor.check()['resultados'][0]
        with monitor.db() as db:
            db.execute('UPDATE jobs SET created=created-86400 WHERE id=?',(first,))
        assert monitor.check()['resultados'][0]['video_id'] != first


def test_spanish_only_cordoba():
    from lightning_video_engine.app.shorts_spanish import localize_report,screen_es
    r={'motivos':['chuva detectada no radar e raios recentes na região'],'raios':{'dados_atrasados':False,'mais_proximo':None},'nowcasting':None}
    localize_report(r)
    assert r['idioma']=='es-AR'
    assert 'Córdoba, Argentina' in r['roteiro']
    assert 'Protección Civil' in r['roteiro']
    assert 'lluvia detectada por radar' in r['roteiro']
    assert 'Cuéntenos en los comentarios' in r['roteiro']
    assert 'active la campana para recibir la próxima alerta' in r['roteiro']
    assert screen_es('Raios observados')=='Descargas observadas'
    assert screen_es('APRESENTADORA')=='PRESENTADORA'
    r['motivos']=['chuva forte persistente na escala do radar na área monitorada']
    localize_report(r)
    assert 'lluvia fuerte persistente' in r['roteiro']
    r['motivos']=['A atividade elétrica aumentou de 2 para 12 raios na área de 15 quilômetros']
    r['densidade']={'antes_15km':2,'agora_15km':12}
    localize_report(r)
    assert 'aumentó de 2 a 12 descargas' in r['roteiro']


def test_uppercase_spanish_scene_titles():
    from lightning_video_engine.app.shorts_spanish import screen_es
    assert screen_es('RAIOS OBSERVADOS') == 'DESCARGAS OBSERVADAS'
    assert screen_es('RECOMENDAÇÕES FINAIS') == 'RECOMENDACIONES FINALES'


def test_spanish_commercial_cities_and_local_clocks():
    from zoneinfo import ZoneInfo
    from lightning_video_engine.app.shorts_locales import SPANISH_CITIES,city_timezone
    from lightning_video_engine.app.shorts_spanish import localize_report
    assert len(SPANISH_CITIES)==10
    assert len(set(CITIES)-set(SPANISH_CITIES))==47
    for key,(country,tz) in SPANISH_CITIES.items():
        assert key in CITIES
        ZoneInfo(tz)
        r={'cidade':key,'nome':CITIES[key][0],'motivos':[], 'raios':{'dados_atrasados':True},'nowcasting':None}
        localize_report(r)
        assert r['nome'] in r['roteiro'] and country in r['roteiro']
        assert r['idioma'].startswith('es')
        assert r['timezone']==city_timezone(key,CITIES[key][1])


def radar_now(**fields):
    return dict({'coberto': True, 'hora': datetime.now(timezone.utc).timestamp()}, **fields)


class SaoPauloLightning:
    """Strikes `km` away, 3 minutes ago; records the radius asked for. raios_40km is the API's 40 km count."""
    def __init__(self, km, count=7, key='sao-paulo'):
        self.km, self.count, self.queries = km, count, []

    def json(self, path, **query):
        self.queries.append((path, query))
        if path == '/alertas/situacao':
            answer = {'dados_atrasados': False, 'coberto': True, 'raios_15km': 0, 'raios_40km': 300,
                      'mais_proximo': {'km': self.km, 'minutos_atras': 3, 'direcao': 'norte'}}
            if 'raio_km' in query:
                answer.update(raio_km=query['raio_km'], raios_raio=self.count)
            return answer
        return {'agora': None}


def radius_report(api, key='sao-paulo'):
    centre = radar_now(classe=1, nome='moderada', neve=False)
    with patch('lightning_video_engine.app.city_shorts.rain_at', return_value=centre), \
         patch('lightning_video_engine.app.city_shorts.rain_duration', return_value=0), \
         patch('lightning_video_engine.app.city_shorts.rain_approach', return_value=None):
        return evaluate(key, api)


def test_sao_paulo_uses_a_25_km_radius():
    api = SaoPauloLightning(km=20)
    report = radius_report(api)
    assert ('/alertas/situacao', {'lat': CITIES['sao-paulo'][2], 'lon': CITIES['sao-paulo'][3], 'raio_km': 25}) in api.queries
    assert report['gerar'] and report['raio_km'] == 25
    assert report['raios']['raios_40km'] == 7
    assert report['roteiro'].startswith('7 raios em 30 minutos a até 25 quilômetros de São Paulo!')


def test_sao_paulo_ignores_storms_beyond_25_km():
    report = radius_report(SaoPauloLightning(km=30, count=0))
    assert not report['gerar']


def test_sao_paulo_without_the_radius_count_claims_no_number():
    class OldApi(SaoPauloLightning):
        def json(self, path, **query):
            answer = super().json(path, **query)
            answer.pop('raios_raio', None)
            return answer
    report = radius_report(OldApi(km=20))
    assert report['raios']['raios_40km'] is None
    assert report['roteiro'].startswith('Atenção, São Paulo, SP. Monitoramento da área até 25 quilômetros')


def test_other_cities_keep_40_km():
    api = SaoPauloLightning(km=30)
    report = radius_report(api, key='belo-horizonte')
    assert all('raio_km' not in q for p, q in api.queries if p == '/alertas/situacao')
    assert report['gerar'] and report['raio_km'] == 40
    assert report['roteiro'].startswith('300 raios em 30 minutos a até 40 quilômetros de Belo Horizonte!')


def test_south_is_monitored_by_state_and_belo_horizonte_is_not():
    from lightning_video_engine.app.city_shorts import MONITORED, SOUTH_POINTS, SOUTH_STATES
    assert {'sul-pr', 'sul-sc', 'sul-rs'} <= set(MONITORED)
    south_cities = {key for key, city in CITIES.items() if city[1] in ('PR', 'SC', 'RS')}
    assert not south_cities & set(MONITORED)
    assert 'belo-horizonte' not in MONITORED
    assert set(SOUTH_POINTS) == {uf for _, uf, _ in SOUTH_STATES.values()}


def test_state_alert_starts_from_the_point_with_most_lightning(tmp_path):
    counts = {-24.956: 41, -23.425: 7}   # Cascavel and Maringá; every other point has none

    class StateSource:
        def json(self, path, **query):
            if path == '/alertas/situacao':
                count = counts.get(query['lat'], 0)
                return {'dados_atrasados': False, 'coberto': True, 'raios_40km': count, 'raios_15km': count,
                        'mais_proximo': {'km': 6, 'minutos_atras': 3, 'direcao': 'oeste'} if count else None}
            return {'agora': {'risco': 'alta', 'nuvens_de': '2026-11-01T12:00:00Z'}}

    radar = {'coberto': True, 'neve': False, 'classe': 1, 'hora': datetime(2026, 11, 1, 11, 55, tzinfo=timezone.utc).timestamp()}
    monitor = Monitor(StateSource(), tmp_path)
    with patch('lightning_video_engine.app.city_shorts.rain_approach', return_value=None), \
         patch('lightning_video_engine.app.city_shorts.rain_at', return_value=radar), \
         patch('lightning_video_engine.app.city_shorts.rain_duration', return_value=0), \
         patch('lightning_video_engine.app.city_shorts.utc_now', return_value=datetime(2026, 11, 1, 12)):
        report = monitor.evaluate_city('sul-pr')
    assert report['gerar'] and report['cidade'] == 'sul-pr'
    assert (report['nome'], report['uf'], report['lat']) == ('Cascavel', 'PR', -24.956)
    assert report['roteiro'].startswith('41 raios em 30 minutos perto de Cascavel, no Paraná! Alerta de tempestade na Região Sul.')
    assert 'Também há raios perto de Maringá.' in report['roteiro']
    assert report['lugar_titulo'] == 'no Paraná, perto de Cascavel'
    assert report['titulo_tela'] == 'Paraná • Região Sul'
    assert monitor.eligible('sul-pr')


def test_quiet_state_does_not_alert(tmp_path):
    source = Source()
    radar = {'coberto': True, 'neve': False, 'classe': 0, 'hora': datetime(2026, 11, 1, 11, 55, tzinfo=timezone.utc).timestamp()}
    with patch('lightning_video_engine.app.city_shorts.rain_approach', return_value=None), \
         patch('lightning_video_engine.app.city_shorts.rain_at', return_value=radar), \
         patch('lightning_video_engine.app.city_shorts.utc_now', return_value=datetime(2026, 11, 1, 12)):
        report = Monitor(source, tmp_path).evaluate_city('sul-rs')
    assert not report['gerar'] and report['cidade'] == 'sul-rs'


def test_weak_lightning_alert_is_not_queued(tmp_path, monkeypatch):
    monkeypatch.delenv('SHORTS_MIN_STRIKES')
    monitor=Monitor(None,tmp_path)
    now=datetime.now(timezone.utc).isoformat()
    weak={'cidade':'belo-horizonte','gerar':True,'verificado_em':now,'secao':'nowcasting',
          'raios':{'raios_40km':22,'dados_atrasados':False}}
    with patch('threading.Thread.start'):
        result=monitor.check(reports={'belo-horizonte':weak})['resultados'][0]
    assert 'video_id' not in result and '100 raios' in result['suprimido']
    strong=dict(weak,raios={'raios_40km':472,'dados_atrasados':False})
    with patch('threading.Thread.start'):
        assert monitor.check(reports={'belo-horizonte':strong})['resultados'][0]['video_id']


def test_strike_minimum_spares_flood_alerts_and_follows_the_setting(monkeypatch):
    from lightning_video_engine.app.city_shorts import below_strike_minimum
    monkeypatch.delenv('SHORTS_MIN_STRIKES')
    assert below_strike_minimum({'raios':{'raios_40km':1,'dados_atrasados':False}})
    assert below_strike_minimum({'raios':{'raios_40km':500,'dados_atrasados':True}})
    assert not below_strike_minimum({'secao':'alagamentos-sp','raios':{'raios_40km':1}})
    monkeypatch.setenv('SHORTS_MIN_STRIKES','20')
    assert not below_strike_minimum({'raios':{'raios_40km':22,'dados_atrasados':False}})
    monkeypatch.setenv('SHORTS_MIN_STRIKES','x')
    assert below_strike_minimum({'raios':{'raios_40km':99,'dados_atrasados':False}})
