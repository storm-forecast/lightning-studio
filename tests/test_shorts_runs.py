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
