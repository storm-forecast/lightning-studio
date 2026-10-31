import unittest
from lightning_video_engine.app.editorial import validate_scene_evidence
from lightning_video_engine.app.production import fallback_narration
from lightning_video_engine.app.segments import Segment


class SceneEvidenceTests(unittest.TestCase):
    def test_local_fallback_speaks_selected_city(self):
        scene = Segment('04-local-1', 'Local', 'destaque', 'probabilidade',
                        place={'nome': 'São Luís, Maranhão, Brasil'})
        scene.narration = 'O mapa apresenta a previsão de raios.'
        with self.assertRaisesRegex(ValueError, 'omitiu a cidade'):
            validate_scene_evidence(scene)
        scene.narration = fallback_narration(scene, '31/10/2026')
        self.assertIn('São Luís, Maranhão, Brasil', scene.narration)
        validate_scene_evidence(scene)

    def test_missing_city_handles_accents_and_case(self):
        scene = Segment('04-local-1', 'Local', 'destaque', 'probabilidade',
                        place={'nome': 'São Luís, MA'}, narration='Entre os lugares de destaque está SAO LUIS; acompanhe a probabilidade de raios.')
        validate_scene_evidence(scene)

    def test_rejects_false_negative_even_with_empty_polygons(self):
        for count in (0, 3):
            for copy in ('Não há severidade nas regiões do Brasil.',
                         'As regiões não apresentam tempestades.',
                         'O Brasil está sem risco de alagamento.'):
                with self.subTest(count=count, copy=copy):
                    scene = Segment('05-agora', 'Agora', 'nowcasting', 'severidade',
                                    narration=copy, metadata={'polygon_count': count})
                    with self.assertRaises(ValueError):
                        validate_scene_evidence(scene)
                    scene.narration = fallback_narration(scene, '31/10/2026')
                    validate_scene_evidence(scene)
                    self.assertNotIn('não há severidade', scene.narration.casefold())

    def test_observed_fallback_uses_brazilian_places_and_window(self):
        scene = Segment('06-observado', 'Observado', 'observacao', 'agora', evidence={
            'observed': {'inicio': '2026-10-31T12:00:00Z', 'fim': '2026-10-31T13:00:00Z',
                         'regioes': [{'cidade': 'Manaus', 'pais': 'Brasil', 'raios': 42},
                                     {'cidade': 'Lima', 'pais': 'Peru', 'raios': 99}]}})
        text = fallback_narration(scene, '31/10/2026')
        self.assertIn('perto de Manaus, 42 descargas', text)
        self.assertIn('2026-10-31T12:00:00Z', text)
        self.assertNotIn('Lima', text)

    def test_monitoring_does_not_invent_cities_from_polygons(self):
        scene = Segment('05-agora', 'Agora', 'nowcasting', 'severidade', metadata={'polygon_count': 2})
        text = fallback_narration(scene, '31/10/2026')
        self.assertIn('apresenta áreas classificadas', text)
        self.assertIn('não permite atribuir', text)
