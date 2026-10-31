import unittest
from lightning_video_engine.app.segments import Segment
from lightning_video_engine.app.bulletin_context import (
    brazilian_highlights, time_reference, add_time_reference, local_recommendations)
from lightning_video_engine.app.editorial import validate_scene_evidence
from lightning_video_engine.app.production import fallback_narration


class UsefulBulletinTests(unittest.TestCase):
    def rain(self):
        return Segment('01-chuva', 'Chuva', 'previsao', 'chuva-prevista',
                       metadata={'period': '31/10/2026, 00:00 a 23:59 UTC'},
                       evidence={'editorial': {'chuva': {'regioes': [
                           {'cidade': 'Lima', 'pais': 'Peru'},
                           {'cidade': 'Belém', 'pais': 'Brasil'}]}}})

    def test_national_copy_must_mention_a_supplied_brazilian_highlight(self):
        scene = self.rain()
        self.assertEqual(brazilian_highlights(scene), ['Belém'])
        scene.narration = 'O mapa mostra chuva na América do Sul.'
        with self.assertRaisesRegex(ValueError, 'destaques brasileiros'):
            validate_scene_evidence(scene)
        scene.narration = fallback_narration(scene, '31/10/2026')
        validate_scene_evidence(scene)
        self.assertIn('Belém', scene.narration)
        self.assertNotIn('Lima', scene.narration)

    def test_forecast_validity_is_spoken_once_and_not_replaced_by_generation_date(self):
        scene = self.rain()
        scene.narration = 'Chuva na região de Belém.'
        add_time_reference(scene)
        add_time_reference(scene)
        self.assertEqual(scene.narration.count('Validade desta previsão:'), 1)
        self.assertIn('00:00 a 23:59 UTC', scene.narration)

    def test_missing_period_is_explicit_and_unavailable_scene_has_no_validity_claim(self):
        scene = self.rain()
        scene.metadata = {}
        self.assertIn('não pôde ser confirmada', time_reference(scene))
        scene.available = False
        self.assertEqual(time_reference(scene), '')

    def test_observation_window_is_readable_and_preserves_the_actual_day(self):
        scene = Segment('06-observado', 'Observado', 'observacao', 'agora', evidence={
            'observed': {'inicio': '2026-10-30T23:30:00Z', 'fim': '2026-10-31T00:30:00Z'}})
        self.assertIn('30/10/2026 às 23:30 UTC', time_reference(scene))
        self.assertIn('31/10/2026 às 00:30 UTC', time_reference(scene))

    def test_advice_uses_only_available_local_lightning_highlights(self):
        local = Segment('04-local-1', 'Local', 'destaque', 'probabilidade', place={'nome': 'Manaus, Brasil'})
        absent = Segment('04-local-2', 'Local', 'destaque', 'probabilidade', available=False, place={'nome': 'Recife, Brasil'})
        advice = local_recommendations([local, absent])
        self.assertIn('Manaus', advice)
        self.assertNotIn('Recife', advice)
        self.assertIn('se houver tempestade', advice)
        self.assertEqual(local_recommendations([absent]), '')

    def test_missing_nowcasting_time_does_not_claim_current_conditions(self):
        scene = Segment('05-agora', 'Agora', 'nowcasting', 'severidade')
        self.assertIn('não pôde ser confirmada', time_reference(scene))
