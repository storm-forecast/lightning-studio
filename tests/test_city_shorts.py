from datetime import datetime, timezone, timedelta
from unittest.mock import patch
from lightning_video_engine.app.city_shorts import CITIES, Monitor, evaluate


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
    assert len(CITIES) == 23
    assert {'sao-paulo','curitiba','porto-alegre'} <= CITIES.keys()


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
        assert 'aumentou de 2 para 12 raios' in report['roteiro']
        source.incomplete=True
        assert not monitor.evaluate_city('curitiba')['gerar']


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
        assert not monitor.evaluate_city('curitiba')['gerar']


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
    assert 'Inscreva-se no TROVOX TEMPO' in script
    assert 'ative o sino para receber alertas' in script


def test_dedupe_restart(tmp_path):
    monitor=Monitor(None,tmp_path)
    with patch('lightning_video_engine.app.city_shorts.CITIES', {'curitiba':('Curitiba','PR',-25,-49)}), patch.object(monitor,'evaluate_city', return_value={'cidade':'curitiba','gerar':True}), patch('threading.Thread.start'):
        first=monitor.check()['resultados'][0]['video_id']
        assert monitor.check()['resultados'][0]['suprimido']
    assert Monitor(None,tmp_path).get(first)['estado']=='falhou'


def test_daily_limit_survives_new_monitor(tmp_path):
    monitor=Monitor(None,tmp_path)
    with patch('lightning_video_engine.app.city_shorts.CITIES', {'curitiba':('Curitiba','PR',-25,-49)}), patch.object(monitor,'evaluate_city', return_value={'cidade':'curitiba','gerar':True}), patch('threading.Thread.start'):
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
    assert 'active la campana para recibir alertas' in r['roteiro']
    assert screen_es('Raios observados')=='Descargas observadas'
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
    assert len(set(CITIES)-set(SPANISH_CITIES))==13
    for key,(country,tz) in SPANISH_CITIES.items():
        assert key in CITIES
        ZoneInfo(tz)
        r={'cidade':key,'nome':CITIES[key][0],'motivos':[], 'raios':{'dados_atrasados':True},'nowcasting':None}
        localize_report(r)
        assert r['nome'] in r['roteiro'] and country in r['roteiro']
        assert r['idioma'].startswith('es')
        assert r['timezone']==city_timezone(key,CITIES[key][1])
