import json
import tempfile
import threading
import unittest
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

from lightning_video_engine.app import city_shorts, shorts_runs


def alert(key, age=0):
    checked = city_shorts.utc_now() - timedelta(seconds=age)
    return {'cidade': key, 'verificado_em': checked.isoformat() + 'Z', 'gerar': True}


class ScanDeadline(unittest.TestCase):
    def test_slow_city_is_reported_without_blocking_the_pass(self):
        release = threading.Event()
        with tempfile.TemporaryDirectory() as folder:
            monitor = shorts_runs.DeferredMonitor(object(), folder)

            def evaluate(key):
                if key == 'salvador':
                    release.wait(5)
                return alert(key) if key == 'rio-de-janeiro' else dict(alert(key), gerar=False)
            with patch.object(monitor, 'eligible', return_value=True), \
                    patch.object(monitor, 'evaluate_city', side_effect=evaluate):
                scan = shorts_runs.scan_cities(monitor, object(), deadline=1)
            release.set()
        self.assertEqual(scan['candidatas'], ['rio-de-janeiro'])
        self.assertIn({'cidade': 'salvador', 'erro': 'sem resposta no prazo da varredura'}, scan['erros'])


class SaoPauloFloodAlerts(unittest.TestCase):
    AREA = [{'id': 'alagamento-0', 'geometria': {'type': 'Point', 'coordinates': [-46.6, -23.5]}}]
    ZONES = [{'zona_id': 'flood-a'}]

    def scan(self, report):
        with tempfile.TemporaryDirectory() as folder:
            monitor = shorts_runs.DeferredMonitor(object(), folder)
            with patch.object(monitor, 'eligible', side_effect=lambda key: key == 'sp-sao-paulo'), \
                    patch.object(monitor, 'evaluate_city', return_value=report), \
                    patch('lightning_video_engine.app.sp_flood_zones.confirmed_zones', return_value=self.ZONES):
                return shorts_runs.scan_cities(monitor, object(), self.AREA, deadline=5)

    def test_polygon_without_radar_rain_never_generates_an_alert(self):
        report = dict(alert('sp-sao-paulo'), gerar=False, motivos=[])
        self.assertEqual(self.scan(report)['candidatas'], [])
        self.assertFalse(report['gerar'])
        self.assertNotIn('zona_id', report)

    def test_polygon_with_radar_rain_generates_and_keeps_the_real_reason(self):
        reason = 'chuva forte persistente com potencial de alagamento no município'
        report = dict(alert('sp-sao-paulo'), motivos=[reason])
        self.assertEqual(self.scan(report)['candidatas'], ['sp-sao-paulo'])
        self.assertEqual(report['zona_id'], 'flood-a')
        self.assertEqual(report['motivos'][0], reason)

    def test_changed_polygon_cannot_repeat_the_alert_the_same_day(self):
        with tempfile.TemporaryDirectory() as folder:
            monitor = city_shorts.Monitor(object(), Path(folder))
            first = dict(alert('sp-sao-paulo'), zona_id='flood-a', motivos=['chuva'])
            second = dict(alert('sp-sao-paulo'), zona_id='flood-b', motivos=['chuva'])
            with patch('threading.Thread.start'):
                created = monitor.check(reports={'sp-sao-paulo': first})['resultados'][0]
                repeated = monitor.check(reports={'sp-sao-paulo': second})['resultados'][0]
        self.assertIn('video_id', created)
        self.assertNotIn('video_id', repeated)
        self.assertIn('suprimido', repeated)

    def test_internal_wording_is_never_narrated(self):
        class Source:
            def json(self, path, **query):
                return {'dados_atrasados': False, 'coberto': True, 'mais_proximo': None, 'agora': None}
        with patch.object(city_shorts, 'rain_at', return_value=None), patch.object(city_shorts, 'rain_approach', return_value=None):
            report = city_shorts.evaluate('sp-sao-paulo', Source())
        self.assertFalse(report['gerar'])
        self.assertNotIn('gatilho', report['roteiro'].lower())

    def test_flood_alert_caption_does_not_say_storm(self):
        from lightning_video_engine.app import instagram
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            (directory / 'alerta.json').write_text(json.dumps({'nome': 'São Paulo', 'uf': 'SP', 'roteiro': 'Texto.', 'secao': 'alagamentos-sp'}))
            with patch.object(instagram, 'publish_reel', return_value={'url': 'x'}) as reel:
                instagram.publish_short(directory)
        caption = reel.call_args[0][1]
        self.assertIn('risco de alagamento', caption)
        self.assertNotIn('tempestade', caption)


class PublishCities(unittest.TestCase):
    def test_stale_alert_is_deferred_and_does_not_reserve_the_day(self):
        with tempfile.TemporaryDirectory() as folder:
            monitor = shorts_runs.DeferredMonitor(object(), folder)
            with patch.object(city_shorts.Monitor, 'work') as work:
                lines, failed = shorts_runs.publish_cities(monitor, Path(folder), {'salvador': alert('salvador', 600)})
            work.assert_not_called()
            self.assertFalse(failed)
            self.assertTrue(monitor.eligible('salvador'))

    def test_failed_upload_releases_the_city(self):
        with tempfile.TemporaryDirectory() as folder, \
                patch.dict('os.environ', {'SHORTS_AUTO_PUBLISH': 'true'}), \
                patch.object(city_shorts, 'render'), \
                patch('lightning_video_engine.app.youtube.publish_short', side_effect=RuntimeError('HTTP 500')):
            monitor = shorts_runs.DeferredMonitor(object(), folder)
            lines, failed = shorts_runs.publish_cities(monitor, Path(folder), {'salvador': alert('salvador')})
            self.assertTrue(failed)
            self.assertTrue(monitor.eligible('salvador'))

    def test_youtube_limit_never_pauses_and_releases_the_city_without_instagram(self):
        from lightning_video_engine.app import youtube
        with tempfile.TemporaryDirectory() as folder, \
                patch.dict('os.environ', {'SHORTS_AUTO_PUBLISH': 'true', 'INSTAGRAM_ACCESS_TOKEN': ''}), \
                patch.object(city_shorts, 'render'), \
                patch('lightning_video_engine.app.youtube.publish_short', side_effect=youtube.QuotaExceeded('quotaExceeded')):
            monitor = shorts_runs.DeferredMonitor(object(), folder)
            shorts_runs.publish_cities(monitor, Path(folder), {'salvador': alert('salvador')})
            self.assertTrue(monitor.eligible('salvador'))
            with patch.object(city_shorts.Monitor, 'work') as work:
                shorts_runs.publish_cities(monitor, Path(folder), {'salvador': alert('salvador')})
            work.assert_called_once()
