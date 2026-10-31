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


class ReadableTimesTests(unittest.TestCase):
    def test_z_and_offsets_use_the_same_utc_instant(self):
        from lightning_video_engine.app.bulletin_context import readable_times
        expected = '31/10/2026 às 14:30 UTC'
        self.assertEqual(readable_times('2026-10-31T14:30:00Z'), expected)
        self.assertEqual(readable_times('2026-10-31T11:30:00-03:00'), expected)

    def test_midnight_conversion_preserves_day_and_removes_duplicate_utc(self):
        from lightning_video_engine.app.bulletin_context import readable_times
        self.assertEqual(readable_times('2026-10-31T23:30:00-03:00 UTC'), '01/11/2026 às 02:30 UTC')

    def test_clock_z_and_unrelated_place_names(self):
        from lightning_video_engine.app.bulletin_context import readable_times
        self.assertEqual(readable_times('Zé Doca: 14:30Z; até 15:30 UTC.'), 'Zé Doca: 14:30 UTC; até 15:30 UTC.')


class BulletinPeriodDedupTests(unittest.TestCase):
    def test_repeated_period_is_spoken_once_but_changed_period_is_kept(self):
        from lightning_video_engine.app.bulletin_context import add_time_reference
        seen = set()
        scenes = [Segment(str(i), 'Teste', 'previsao', 'probabilidade', narration='Destaque local.',
                          metadata={'period': period})
                  for i, period in enumerate(('31/10/2026 UTC', '31/10/2026 UTC', '01/11/2026 UTC'))]
        for scene in scenes:
            add_time_reference(scene, seen)
        self.assertIn('Validade desta previsão', scenes[0].narration)
        self.assertNotIn('Validade desta previsão', scenes[1].narration)
        self.assertIn('01/11/2026 UTC', scenes[2].narration)
        self.assertEqual(scenes[1].metadata['period'], '31/10/2026 UTC')

    def test_resumed_script_removes_duplicate_suffix_without_cutting_weather(self):
        from lightning_video_engine.app.bulletin_context import add_time_reference
        scene = Segment('local', 'Teste', 'destaque', 'probabilidade',
                        narration='Belém é destaque. Validade desta previsão: 31/10/2026 UTC.',
                        metadata={'period': '31/10/2026 UTC'})
        seen = {'Validade desta previsão: 31/10/2026 UTC.'}
        add_time_reference(scene, seen)
        self.assertEqual(scene.narration, 'Belém é destaque.')


class BrasiliaPresentationTests(unittest.TestCase):
    def test_utc_has_explicit_brasilia_conversion(self):
        from lightning_video_engine.app.bulletin_context import readable_times
        self.assertEqual(readable_times('15:00 UTC', include_brasilia=True),
                         '15:00 UTC (12:00 no horário de Brasília)')

    def test_conversion_preserves_previous_date_and_is_idempotent(self):
        from lightning_video_engine.app.bulletin_context import readable_times
        text = readable_times('2026-11-01T01:30:00Z', include_brasilia=True)
        self.assertIn('22:30 de 31/10/2026, horário de Brasília', text)
        self.assertEqual(readable_times(text, include_brasilia=True), text)
        self.assertIn('dia anterior', readable_times('01:00 UTC', include_brasilia=True))

    def test_structured_window_takes_precedence_over_ambiguous_label(self):
        scene=Segment('rain', 'Chuva', 'previsao', 'chuva-prevista', metadata={
            'period': 'hoje', 'forecast_window': {'inicio':'2026-10-31T00:00:00Z','fim':'2026-11-01T00:00:00Z'}})
        self.assertIn('31/10/2026 às 00:00 UTC', time_reference(scene))
        self.assertIn('01/11/2026 às 00:00 UTC', time_reference(scene))
