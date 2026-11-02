import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from lightning_video_engine.app import shorts_runs, world_alerts, world_shorts


def situation(**values):
    base = {'coberto': True, 'dados_atrasados': False, 'janela_incompleta': False, 'raios_40km': 20}
    return dict(base, **values)


class LightningTriggers(unittest.TestCase):
    def triggers(self, value):
        with patch.object(world_alerts, 'urlopen') as opened:
            opened.return_value.__enter__.return_value.read.return_value = json.dumps(value).encode()
            with patch.object(world_alerts.json, 'load', return_value=value):
                return world_alerts._lightning_triggers(0, 0)[0]

    def test_recent_strike_near_the_centre_is_a_storm_over_the_city(self):
        self.assertEqual(self.triggers(situation(mais_proximo={'km': 6, 'minutos_atras': 3})), ['storm_overhead'])

    def test_storm_moving_in_within_the_hour_is_approaching(self):
        value = situation(mais_proximo={'km': 21, 'minutos_atras': 2, 'direcao': 'sudoeste'},
                          tendencia={'sentido': 'aproximando', 'km_agora': 21, 'velocidade_kmh': 24, 'minutos_ate_15km': 15})
        self.assertEqual(self.triggers(value), ['storm_approaching'])

    def test_departing_or_stale_storm_does_not_trigger(self):
        leaving = situation(mais_proximo={'km': 30, 'minutos_atras': 27},
                            tendencia={'sentido': 'afastando', 'km_agora': 68})
        self.assertEqual(self.triggers(leaving), [])
        stale = situation(dados_atrasados=True, mais_proximo={'km': 2, 'minutos_atras': 1})
        self.assertEqual(self.triggers(stale), [])


class Priority(unittest.TestCase):
    def test_warnings_and_storms_come_before_watches_and_forecasts(self):
        rows = [{'id': 'f', 'nivel': 'alta', 'gatilhos': ['heavy_rain']},
                {'id': 'w', 'nivel': 'alta', 'gatilhos': ['official_watch']},
                {'id': 'a', 'nivel': 'alta', 'gatilhos': ['storm_approaching']},
                {'id': 'o', 'nivel': 'alta', 'gatilhos': ['official_warning']}]
        with patch.object(world_shorts, 'alerts', return_value=rows):
            self.assertEqual([row['id'] for row in world_shorts.candidates()], ['o', 'a', 'w', 'f'])


class Escalation(unittest.TestCase):
    def publish(self, folder, history, rows):
        Path(folder, 'published.json').write_text(json.dumps(history))
        published = []
        with patch.object(world_shorts, 'candidates', return_value=rows), \
                patch.object(world_shorts, 'report', side_effect=lambda row: {'cidade': row['id']}), \
                patch.object(world_shorts, 'render'), \
                patch.object(shorts_runs, 'publish_short', side_effect=lambda d, **_: published.append(d) or {'url': 'u'}):
            shorts_runs.publish_world(folder)
        return published

    def test_storm_after_a_forecast_short_publishes_again_but_not_twice(self):
        today = datetime.now(timezone.utc).date().isoformat()
        storm = {'id': 'miami', 'gatilhos': ['storm_approaching']}
        with tempfile.TemporaryDirectory() as folder:
            self.assertEqual(self.publish(folder, {'miami': today}, [storm]), [])
            forecast = {'miami': {'dia': today, 'prioridade': 4}}
            self.assertEqual(len(self.publish(folder, forecast, [storm])), 1)
            saved = json.loads(Path(folder, 'published.json').read_text())
            self.assertEqual(saved['miami'], {'dia': today, 'prioridade': 2})
            self.assertEqual(self.publish(folder, saved, [storm]), [])

    def test_several_urgent_cities_publish_in_the_same_pass(self):
        rows = [{'id': f'c{i}', 'gatilhos': ['storm_overhead']} for i in range(4)]
        with tempfile.TemporaryDirectory() as folder:
            self.assertEqual(len(self.publish(folder, {}, rows)), 3)
