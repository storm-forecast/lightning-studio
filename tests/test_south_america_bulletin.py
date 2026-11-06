from datetime import date, datetime, timezone
import json

import numpy as np
import pytest

from lightning_video_engine.app import south_america_bulletin as bulletin
from lightning_video_engine.app.youtube import bulletin_metadata


def row(**fields):
    base = {'tmax': 30.0, 'tmax_em': None, 'tmax_lat': -10., 'tmax_lon': -50., 'rh': 55, 'rh_em': None, 'rh_lat': -10., 'rh_lon': -50.,
            'chuva': 0, 'chuva_em': None, 'chuva_lat': -10., 'chuva_lon': -50., 'acima38': 0, 'acima35': 0, 'abaixo30': 0, 'abaixo20': 0,
            'perigo': 0, 'atencao': 0, 'alta': 0, 'tempestade': 0, 'alta_seca': 0, 'alta_total': 0}
    return {**base, **fields}


def table(**states):
    out = {'uf:' + name: {'hoje': row(), 'amanha': row()} for name in bulletin.UF}
    out.update({'pais:' + name: {'hoje': row(), 'amanha': row()} for name in bulletin.CC})
    for name, fields in states.items():
        out['uf:' + name.replace('_', ' ')] = {'hoje': row(**fields), 'amanha': row(**fields)}
    return out


def full_text(script):
    return ' '.join(text for _, text in script)


def test_script_has_every_scene_in_order_on_a_calm_day():
    script = bulletin.write_narration(table(), date(2026, 11, 7), date(2026, 11, 8))
    assert [name for name, _ in script] == list(bulletin.NUMBER_ORDER)
    text = full_text(script)
    assert 'Nenhum estado tem área grande' in text and 'não há grandes áreas' in text
    assert 'None' not in text and 'nan' not in text


def test_script_names_only_what_the_numbers_say():
    extreme = table(Bahia={'tmax': 41.2, 'tmax_em': 'Casa Nova', 'rh': 10, 'rh_em': 'Casa Nova', 'perigo': 40, 'atencao': 70, 'acima38': 30, 'abaixo30': 70},
                    Santa_Catarina={'chuva': 80, 'chuva_em': 'Campos Novos', 'tempestade': 94})
    text = full_text(bulletin.write_narration(extreme, date(2026, 11, 7), date(2026, 11, 8)))
    assert 'região de Casa Nova, na Bahia, com 41 graus' in text
    assert 'Santa Catarina, com 94 por cento do território' in text
    assert 'alagamentos e deslizamentos' in text
    assert 'O perigo maior amanhã está na Bahia' in text
    assert 'Na Bahia, 30 por cento' in text


def test_no_technical_model_names_reach_the_public():
    script = bulletin.write_narration(table(), date(2026, 11, 7), date(2026, 11, 8))
    text = bulletin.youtube_text(table(), date(2026, 11, 7), date(2026, 11, 8))
    public = full_text(script) + text['title'] + text['description']
    assert 'GFS' not in public and 'ECENS' not in public and 'Modelo 1' not in public


def test_days_follow_brasilia_not_utc():
    days = bulletin.forecast_days(datetime(2026, 11, 7, 1, 0, tzinfo=timezone.utc))
    assert [d[0] for d in days] == [date(2026, 11, 6), date(2026, 11, 7)]
    assert days[0][1] == datetime(2026, 11, 6, 3) and days[0][2] == datetime(2026, 11, 7, 3)


def test_humidity_is_full_at_the_dew_point_and_low_in_dry_heat():
    assert bulletin.humidity(np.array(25.), np.array(25.)) == pytest.approx(100)
    assert bulletin.humidity(np.array(40.), np.array(5.)) == pytest.approx(12, abs=2)


def test_a_place_name_must_be_near_and_in_the_same_region():
    places = [(-9.17, -40.97, 'Casa Nova', 'BR', 'Bahia', 72086), (-9.2, -40.9, 'Pequena', 'BR', 'Bahia', 5000)]
    assert bulletin.place_near(-9.2, -41.0, places) == 'Casa Nova'
    assert bulletin.place_near(-15.0, -50.0, places) is None
    assert bulletin.place_near(-9.2, -41.0, []) is None


def test_youtube_uses_the_written_title_and_description(tmp_path):
    (tmp_path / 'youtube-metadata.json').write_text(json.dumps({'title': 'Título do dia', 'description': 'Texto do dia'}))
    metadata = bulletin_metadata(tmp_path, datetime(2026, 11, 7, tzinfo=timezone.utc), privacy='public')
    assert metadata['snippet']['title'] == 'Título do dia' and metadata['snippet']['description'] == 'Texto do dia'


def test_old_bulletin_text_stays_when_nothing_was_written(tmp_path):
    metadata = bulletin_metadata(tmp_path, datetime(2026, 11, 7, tzinfo=timezone.utc), privacy='public')
    assert metadata['snippet']['title'].startswith('Boletim do tempo')
