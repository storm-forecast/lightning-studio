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
                    'tendencia': {'sentido': 'aproximando'} if self.count else None, 'mais_proximo': None}
        return {'agora': {'risco': self.risk, 'nuvens_de': '2026-11-01T12:00:00Z'}}


def test_allowlist():
    assert len(CITIES) == 23
    assert {'sao-paulo','curitiba','porto-alegre'} <= CITIES.keys()


def test_triggers_and_staleness():
    source=Source()
    with patch('lightning_video_engine.app.city_shorts.rain_approach', return_value=None), patch('lightning_video_engine.app.city_shorts.rain_at', return_value=None), patch('lightning_video_engine.app.city_shorts.utc_now', return_value=datetime(2026,11,1,12)):
        assert not evaluate('curitiba',source)['gerar']
        source.count=3
        assert evaluate('curitiba',source)['gerar']
        source.stale=True
        assert not evaluate('curitiba',source)['gerar']
        source.risk='alta'
        assert not evaluate('curitiba',source)['gerar']


def test_recent_lightning_within_fifteen_km_triggers_even_when_stationary():
    source=Source()
    source.count=3
    source.risk='alta'
    def close_lightning(path, **query):
        if path == '/alertas/situacao':
            return {'dados_atrasados':False,'coberto':True,'raios_40km':3,
                    'tendencia':{'sentido':'parada'},'mais_proximo':{'km':9,'minutos_atras':3,'direcao':'oeste'}}
        return {'agora':{'risco':'alta','nuvens_de':'2026-11-01T12:00:00Z'}}
    source.json=close_lightning
    with patch('lightning_video_engine.app.city_shorts.rain_approach', return_value=None), patch('lightning_video_engine.app.city_shorts.rain_at', return_value=None), patch('lightning_video_engine.app.city_shorts.utc_now', return_value=datetime(2026,11,1,12)):
        assert evaluate('curitiba',source)['gerar']


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
    with patch('lightning_video_engine.app.city_shorts.rain_approach', return_value=None), patch('lightning_video_engine.app.city_shorts.rain_at', return_value=None), patch('lightning_video_engine.app.city_shorts.utc_now', return_value=datetime(2026,11,1,12)):
        script=evaluate('curitiba',source)['roteiro']
    assert 'Inscreva-se no TROVOX TEMPO' in script
    assert 'ative o sino para receber alertas' in script


def test_dedupe_restart(tmp_path):
    monitor=Monitor(None,tmp_path)
    with patch('lightning_video_engine.app.city_shorts.CITIES', {'curitiba':('Curitiba','PR',-25,-49)}), patch('lightning_video_engine.app.city_shorts.evaluate', return_value={'cidade':'curitiba','gerar':True}), patch('threading.Thread.start'):
        first=monitor.check()['resultados'][0]['video_id']
        assert monitor.check()['resultados'][0]['suprimido']
    assert Monitor(None,tmp_path).get(first)['estado']=='falhou'


def test_daily_limit_survives_new_monitor(tmp_path):
    monitor=Monitor(None,tmp_path)
    with patch('lightning_video_engine.app.city_shorts.CITIES', {'curitiba':('Curitiba','PR',-25,-49)}), patch('lightning_video_engine.app.city_shorts.evaluate', return_value={'cidade':'curitiba','gerar':True}), patch('threading.Thread.start'):
        first=monitor.check()['resultados'][0]['video_id']
        item=monitor.get(first);item['estado']='concluido';monitor.save(item)
        assert 'suprimido' in monitor.check()['resultados'][0]
        with monitor.db() as db:
            db.execute('UPDATE jobs SET created=created-86400 WHERE id=?',(first,))
        assert monitor.check()['resultados'][0]['video_id'] != first


def test_spanish_only_cordoba():
    from lightning_video_engine.app.shorts_spanish import localize_report,screen_es
    r={'motivos':['tempestade com atividade elétrica se aproximando da região'],'raios':{'dados_atrasados':False,'mais_proximo':None},'nowcasting':None}
    localize_report(r)
    assert r['idioma']=='es-AR'
    assert 'Córdoba, Argentina' in r['roteiro']
    assert 'Protección Civil' in r['roteiro']
    assert 'active la campana para recibir alertas' in r['roteiro']
    assert screen_es('Raios observados')=='Descargas observadas'


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
