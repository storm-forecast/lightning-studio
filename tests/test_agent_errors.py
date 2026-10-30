import io
import json
import unittest
from unittest.mock import patch
from lightning_video_engine.app.lightning_agent import LightningAgentClient

class AgentErrors(unittest.TestCase):
    def test_technical_message_is_retried_instead_of_narrated(self):
        messages=['Muitas perguntas em sequência agora. Aguarde alguns segundos e tente de novo.',
                  'A previsão indica possibilidade de raios.']
        responses=[io.BytesIO(json.dumps({'resposta':s}).encode()) for s in messages]
        with patch('lightning_video_engine.app.lightning_agent.urlopen',side_effect=responses) as fetch,\
             patch('lightning_video_engine.app.lightning_agent.time.sleep'):
            result=LightningAgentClient('https://example.invalid','https://example.invalid/app/').perguntar('teste')
        self.assertEqual(result['resposta'],messages[1]);self.assertEqual(fetch.call_count,2)

    def test_repeated_technical_answers_fail_explicitly(self):
        responses=[io.BytesIO(json.dumps({'resposta':'A Groq não respondeu em 20s. Tente de novo.'}).encode()) for _ in range(3)]
        with patch('lightning_video_engine.app.lightning_agent.urlopen',side_effect=responses),\
             patch('lightning_video_engine.app.lightning_agent.time.sleep'):
            with self.assertRaisesRegex(RuntimeError,'três tentativas'):
                LightningAgentClient('https://example.invalid','https://example.invalid/app/').perguntar('teste')
