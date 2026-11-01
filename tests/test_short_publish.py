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
    with patch('subprocess.check_output',return_value=json.dumps(probe).encode()), patch.object(youtube,'access_token',return_value='token'), patch.object(youtube,'authorized_channel',return_value=('canal','TROVOX')), patch.object(youtube,'upload',return_value={'id':'abc','status':{'privacyStatus':'public'}}) as upload:
        assert youtube.publish_short(tmp_path,ENV)['privacy']=='public'
        assert youtube.publish_short(tmp_path,ENV)['video_id']=='abc'
        assert upload.call_count==1
        assert upload.call_args.args[1]['status']['containsSyntheticMedia']

def test_expired_alert_refused(tmp_path):
    (tmp_path/'alerta.json').write_text(json.dumps({'verificado_em':'2020-01-01T00:00:00Z','gerar':True}))
    with patch.object(youtube,'upload') as upload, pytest.raises(youtube.YouTubeError,match='expirado'):
        youtube.publish_short(tmp_path,ENV)
    upload.assert_not_called()
