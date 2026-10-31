import unittest
from lightning_video_engine.app.editorial import BRAZIL_REGIONS, regional_scene_direction


class RegionalDirectionTests(unittest.TestCase):
    def test_both_national_forecasts_cover_five_regions_with_more_time(self):
        for scene_id in ('01-chuva', '02-ecens'):
            with self.subTest(scene=scene_id):
                text = regional_scene_direction(scene_id)
                for region in BRAZIL_REGIONS:
                    self.assertIn(region, text)
                self.assertIn('120 palavras', text)
                self.assertIn('não prova ausência de risco', text)
                self.assertIn('sem inventar um ranking', text)

    def test_lightning_panorama_excludes_rain(self):
        self.assertIn('não fale de chuva', regional_scene_direction('02-ecens'))
        self.assertIn('acumulados somente quando confirmados', regional_scene_direction('01-chuva'))

    def test_local_and_monitoring_scenes_keep_short_budget(self):
        for scene_id in ('04-local-1', '11-recomendacoes'):
            with self.subTest(scene=scene_id):
                text = regional_scene_direction(scene_id)
                self.assertIn('45 palavras', text)
                self.assertIn('não repita o panorama', text)
                self.assertNotIn('120 palavras', text)

    def test_nowcasting_uses_separate_products_and_requires_prior_forecast_proof(self):
        products = {'05-agora': 'polígonos', '06-observado': 'contagens', '07-alagamento': 'potencial de alagamento'}
        for scene, product in products.items():
            with self.subTest(scene=scene):
                text = regional_scene_direction(scene)
                self.assertIn(product, text)
                self.assertIn('100 palavras', text)
                self.assertIn('emitida antes dos eventos', text)
                self.assertIn('toda a janela observada', text)
                self.assertIn('cada produto tem sua própria cena', text)
