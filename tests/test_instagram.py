import json
from unittest.mock import patch
from lightning_video_engine.app import instagram

ENV={'INSTAGRAM_ACCESS_TOKEN':'token','INSTAGRAM_USER_ID':'conta'}
REPORT={'nome':'Curitiba','uf':'PR','roteiro':'Alerta de teste.','titulo_short':'Curitiba (PR): alerta #Shorts'}

def test_short_reel_and_idempotency(tmp_path):
    (tmp_path/'alerta.json').write_text(json.dumps(REPORT))
    (tmp_path/'short.mp4').write_bytes(b'mp4')
    with patch.object(instagram,'authorized_account',return_value=('conta','trovox')), patch.object(instagram,'_request',return_value={'success':True}) as upload, patch.object(instagram,'_graph',side_effect=[{'id':'c1'},{'status_code':'FINISHED'},{'id':'m1'},{'permalink':'https://instagram.com/reel/x'}]) as graph:
        assert instagram.publish_short(tmp_path,ENV)['url']=='https://instagram.com/reel/x'
        assert instagram.publish_short(tmp_path,ENV)['media_id']=='m1'
        assert upload.call_count==1
        caption=graph.call_args_list[0].kwargs['caption']
        assert '#Shorts' not in caption and 'Alerta de teste.' in caption

def test_inaccessible_account_refused(tmp_path):
    (tmp_path/'alerta.json').write_text(json.dumps(REPORT))
    (tmp_path/'short.mp4').write_bytes(b'mp4')
    with patch.object(instagram,'_request',side_effect=instagram.InstagramError('HTTP 400')) as request:
        assert 'HTTP 400' in instagram.cross_post(tmp_path,ENV)['error']
    assert request.call_count==1

def test_token_kind_selects_host():
    assert instagram._host('IGQ...')=='graph.instagram.com'
    assert instagram._host('EAA...')=='graph.facebook.com'

def test_cross_post_disabled_without_token(tmp_path):
    assert instagram.cross_post(tmp_path,{}) is None
