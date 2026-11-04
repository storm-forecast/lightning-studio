import json
from datetime import datetime, timezone
from unittest.mock import patch
import pytest
from lightning_video_engine.app import youtube

ENV={'YOUTUBE_CLIENT_ID':'id','YOUTUBE_CLIENT_SECRET':'s','YOUTUBE_REFRESH_TOKEN':'r','YOUTUBE_CHANNEL_ID':'canal'}

def test_short_upload_and_idempotency(tmp_path):
    report={'verificado_em':datetime.now(timezone.utc).isoformat(),'gerar':True,'nome':'Curitiba','uf':'PR','roteiro':'Alerta de teste.'}
    (tmp_path/'alerta.json').write_text(json.dumps(report))
    probe={'streams':[{'codec_type':'video','height':1280,'width':720}],'format':{'duration':'35'}}
    with patch('subprocess.check_output',return_value=json.dumps(probe).encode()), patch.object(youtube,'access_token',return_value='token'), patch.object(youtube,'authorized_channel',return_value=('canal','TROVOX')), patch.object(youtube,'alerts_published_today',return_value=0), patch.object(youtube,'upload',return_value={'id':'abc','status':{'privacyStatus':'public'}}) as upload:
        assert youtube.publish_short(tmp_path,ENV)['privacy']=='public'
        assert youtube.publish_short(tmp_path,ENV)['video_id']=='abc'
        assert upload.call_count==1
        assert upload.call_args.args[1]['status']['containsSyntheticMedia']

def publish_with_count(tmp_path,count,**kwargs):
    report={'verificado_em':datetime.now(timezone.utc).isoformat(),'gerar':True,'nome':'Curitiba','uf':'PR','roteiro':'Alerta.'}
    (tmp_path/'alerta.json').write_text(json.dumps(report))
    probe={'streams':[{'codec_type':'video','height':1280,'width':720}],'format':{'duration':'35'}}
    env=dict(ENV,**{f"WORLD_{k}":v for k,v in ENV.items()})
    with patch('subprocess.check_output',return_value=json.dumps(probe).encode()), patch.object(youtube,'access_token',return_value='token'), patch.object(youtube,'authorized_channel',return_value=('canal','TROVOX')), patch.object(youtube,'alerts_published_today',**count), patch.object(youtube,'upload',return_value={'id':'abc','status':{'privacyStatus':'public'}}) as upload:
        try:
            youtube.publish_short(tmp_path,env,**kwargs)
        except youtube.QuotaExceeded as exc:
            return upload,str(exc)
    return upload,None

def test_seventh_alert_goes_out_and_the_eighth_does_not(tmp_path):
    upload,error=publish_with_count(tmp_path,{'return_value':6})
    assert upload.call_count==1 and error is None
    (tmp_path/'youtube-short.json').unlink()
    upload,error=publish_with_count(tmp_path,{'return_value':7})
    upload.assert_not_called()
    assert '7 alertas' in error

def test_unknown_count_means_no_upload(tmp_path):
    upload,error=publish_with_count(tmp_path,{'side_effect':OSError('rede')})
    upload.assert_not_called()
    assert 'indisponível' in error

def test_global_channel_is_not_capped(tmp_path):
    upload,error=publish_with_count(tmp_path,{'return_value':50},prefix='WORLD_YOUTUBE',brand='TROVOX GLOBAL')
    assert upload.call_count==1 and error is None

def test_only_todays_alert_titles_are_counted():
    def video(title,published):
        return {'snippet':{'title':title,'publishedAt':published}}
    videos=[video('São Paulo (SP): alerta de tempestade | 04/11 08:20 #Shorts','2026-11-04T11:22:12Z'),
            video('Campinas (SP): risco de alagamento | 04/11 01:10 #Shorts','2026-11-04T04:10:00Z'),
            # 23:50 in Brasília on the 3rd, although already the 4th in UTC.
            video('Gramado (RS): alerta de tempestade | 03/11 23:50 #Shorts','2026-11-04T02:50:00Z'),
            video('Tornado em Chapecó: Trovox Tempo previu risco alto na véspera #Shorts','2026-11-04T12:00:00Z'),
            video('Boletim do tempo 04/11','2026-11-04T08:30:00Z')]
    replies=[({},{'items':[{'contentDetails':{'relatedPlaylists':{'uploads':'UU'}}}]}),({},{'items':videos})]
    now=datetime(2026,11,4,15,0,tzinfo=timezone.utc)
    with patch.object(youtube,'_request',side_effect=replies):
        assert youtube.alerts_published_today('token','canal',now)==2

def test_expired_alert_refused(tmp_path):
    (tmp_path/'alerta.json').write_text(json.dumps({'verificado_em':'2020-01-01T00:00:00Z','gerar':True}))
    with patch.object(youtube,'upload') as upload, pytest.raises(youtube.YouTubeError,match='expirado'):
        youtube.publish_short(tmp_path,ENV)
    upload.assert_not_called()
