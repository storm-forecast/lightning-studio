from datetime import datetime
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
