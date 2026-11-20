import json
from unittest.mock import patch
from lightning_video_engine.app import instagram

ENV={'INSTAGRAM_ACCESS_TOKEN':'token','INSTAGRAM_USER_ID':'conta'}
REPORT={'idioma':'es-VE','nome':'Caracas','pais':'Venezuela','roteiro':'Alerta de teste.','titulo_short':'Caracas: alerta #Shorts'}

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

def test_cross_post_disabled_without_token(tmp_path,capsys,monkeypatch):
    monkeypatch.setattr(instagram,'_warned_missing_token',False)
    assert instagram.cross_post(tmp_path,{}) is None
    assert instagram.cross_post(tmp_path,{}) is None
    assert capsys.readouterr().out.count('INSTAGRAM_ACCESS_TOKEN')==1


def test_portuguese_never_reaches_instagram(tmp_path):
    (tmp_path/'alerta.json').write_text(json.dumps({'nome':'Curitiba','uf':'PR','roteiro':'x'}))
    (tmp_path/'short.mp4').write_bytes(b'mp4')
    with patch.object(instagram,'publish_reel') as reel, patch.object(instagram,'_request') as request:
        assert instagram.cross_post(tmp_path,ENV) is None
        try:
            instagram.publish_short(tmp_path,ENV)
            raise AssertionError('publicou em português')
        except instagram.InstagramError:
            pass
    reel.assert_not_called(); request.assert_not_called()
    assert not (tmp_path/'instagram.json').exists()
