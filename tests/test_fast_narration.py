import io
import json
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from lightning_video_engine.app.lightning_agent import LightningAgentClient


class FastNarrationTests(unittest.TestCase):
    def client(self):
        c = LightningAgentClient('https://example.test', 'https://example.test/app/')
        c.min_interval = 0
        return c

    def test_direct_narration_needs_one_http_request_with_structured_evidence(self):
        with patch('lightning_video_engine.app.lightning_agent.urlopen', return_value=io.BytesIO(b'{"resposta":"Em Belem, acompanhe os avisos."}')) as call:
            result = self.client().narrar('Narre a cena.', {'local': 'Belém'})
        self.assertIn('Belem', result['resposta'])
        self.assertEqual(call.call_count, 1)
        request = call.call_args.args[0]
        self.assertTrue(request.full_url.endswith('/chat/boletim'))
        self.assertEqual(json.loads(request.data)['evidencias']['local'], 'Belém')

    def test_old_api_fallback_is_detected_only_once(self):
        client = self.client()
        missing = HTTPError('https://example.test/chat/boletim', 404, 'Not found', {}, None)
        with patch('lightning_video_engine.app.lightning_agent.urlopen', side_effect=missing) as call, patch.object(client, 'perguntar', return_value={'resposta':'Texto antigo'}) as legacy:
            client.narrar('Narre.', {'local':'Belém'})
            client.narrar('Narre.', {'local':'Manaus'})
        self.assertEqual(call.call_count, 1)
        self.assertEqual(legacy.call_count, 2)
        self.assertIn('Manaus', legacy.call_args.args[0])

    def test_busy_narrator_does_not_start_extra_chat_requests(self):
        client = self.client()
        busy = HTTPError('https://example.test/chat/boletim', 503, 'Unavailable', {}, None)
        with patch('lightning_video_engine.app.lightning_agent.urlopen', side_effect=busy), patch.object(client, 'perguntar') as legacy:
            with self.assertRaises(RuntimeError):
                client.narrar('Narre.', {'local':'Belém'})
        legacy.assert_not_called()
