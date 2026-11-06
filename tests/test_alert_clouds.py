from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest

from lightning_video_engine.app import alert_clouds, city_shorts
from lightning_video_engine.app.alert_clouds import LABELS, choose_scans, palette, panel, scan_angles, scan_start

NOW = datetime(2026, 11, 6, 15, 40, tzinfo=timezone.utc)


def key(moment):
    return ('ABI-L2-CMIPF/x/OR_ABI-L2-CMIPF-M6C13_G19_'
            f"s{moment:%Y%j%H%M}216_e{moment:%Y%j%H%M}536_c{moment:%Y%j%H%M}600.nc")


def scans(last_minutes_ago=10, count=7, gap=10):
    return [key(NOW - timedelta(minutes=last_minutes_ago + gap * i)) for i in reversed(range(count))]


def test_navigation_matches_the_goes_user_guide_example():
    x, y = scan_angles(33.846162, -84.690932, -75.0)
    assert x == pytest.approx(-0.024052, abs=1e-6)
    assert y == pytest.approx(0.095340, abs=1e-6)


def test_scan_time_comes_from_the_file_name():
    assert scan_start(key(NOW)) == NOW


def test_recent_continuous_scans_are_used():
    keys = scans()
    assert choose_scans(keys, NOW) == keys


@pytest.mark.parametrize('keys', [scans(count=3), scans(last_minutes_ago=36), scans(gap=30)])
def test_short_old_or_broken_sequences_are_refused(keys):
    with pytest.raises(ValueError):
        choose_scans(keys, NOW)


def test_colder_tops_never_get_the_clear_sky_colour():
    colours = palette()
    assert colours.shape == (256, 3)
    assert colours[-1].sum() < 150          # +35 C: dark ground
    assert colours[int((95 - 85) / 130 * 255)].sum() > 600   # -85 C: bright top


def report(**fields):
    return dict({'nome': 'Curitiba', 'uf': 'PR', 'raios': {'raios_40km': 12, 'mais_proximo': {'km': 6.2, 'direcao': 'oeste'}},
                 'chuva': {'coberto': True, 'nome': 'forte'}, 'nowcasting': {'deslocamento': {'para': 'leste', 'velocidade_kmh': 30}},
                 'motivos': ['chuva forte persistente na escala do radar na área monitorada'],
                 'recomendacoes': ['Procure abrigo.']}, **fields)


@pytest.mark.parametrize('scene', ['facts', 'protect'])
@pytest.mark.parametrize('language', ['pt', 'es'])
def test_panels_render_with_and_without_optional_data(scene, language):
    labels, moment = LABELS[language], NOW
    assert panel(report(), labels, scene, moment).size == (720, 1280)
    bare = report(raios={}, chuva=None, nowcasting=None, motivos=[])
    assert panel(bare, labels, scene, moment).size == (720, 1280)


def test_languages_carry_the_same_labels():
    assert LABELS['pt'].keys() == LABELS['es'].keys()


class Voice:
    def __init__(self, text, voice):
        pass

    async def save(self, path):
        Path(path).write_bytes(b'mp3')


@pytest.mark.parametrize('failure,expected', [(None, 'nuvens'), (OSError('sem rede'), 'estatico')])
def test_alert_survives_satellite_failure(tmp_path, failure, expected):
    """Clouds are used when they work; a failure must reach the static layout, not lose the alert."""
    alert = {'verificado_em': datetime.now(timezone.utc).replace(tzinfo=None).isoformat() + 'Z',
             'roteiro': 'texto', 'lat': -25.4, 'lon': -49.2}
    reached = []
    with patch('edge_tts.Communicate', Voice), \
         patch.object(alert_clouds, 'render_clouds', side_effect=failure) as clouds, \
         patch('lightning_video_engine.app.regional_map.basemap', side_effect=lambda *a: reached.append('estatico') or (_ for _ in ()).throw(KeyboardInterrupt())):
        try:
            city_shorts.render(tmp_path / 'a', alert, object())
            reached.append('nuvens')
        except KeyboardInterrupt:
            pass
    clouds.assert_called_once()
    assert reached == [expected]
