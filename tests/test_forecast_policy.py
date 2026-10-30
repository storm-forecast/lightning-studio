import unittest
from lightning_video_engine.app.forecast_policy import validate_forecasts, validate_forecast_text, narration_view, validate_narration_layer
from lightning_video_engine.app.segments import Segment

class ForecastPolicyTests(unittest.TestCase):
    def test_rejects_cached_gfs_forecast(self):
        with self.assertRaisesRegex(ValueError,'exclusivamente ECENS'):
            validate_forecasts([Segment('rain','Chuva','previsao','chuva-prevista','gfs',metadata={'source':'gfs'})])

    def test_rejects_wrong_actual_capture_source(self):
        with self.assertRaisesRegex(ValueError,'captura não confirma'):
            validate_forecasts([Segment('rain','Chuva','previsao','chuva-prevista','ecens',metadata={'source':'gfs'})])

    def test_requires_explicit_ai_attribution_in_lightning_opening(self):
        s=Segment('02-ecens','Raios','previsao','deterministico','ecens',narration='Previsão de raios do ECENS.')
        with self.assertRaisesRegex(ValueError,'parâmetros convectivos'):
            validate_forecast_text(s)
        s.narration='Raios previstos pelo modelo de inteligência artificial usando parâmetros convectivos do ECENS.'
        validate_forecast_text(s)

    def test_monitoring_is_not_mislabeled_as_ecens_forecast(self):
        validate_forecasts([Segment('now','Agora','nowcasting','severidade','monitoramento',metadata={'source':'monitoramento'})])

class NarrationLayerTests(unittest.TestCase):
    def scene(self,text,view='deterministico'):
        return Segment('04-local-2','Local','destaque',view,'ecens',narration=text)

    def test_probability_changes_deterministic_map(self):
        s=self.scene('A probabilidade de raios é de setenta e cinco vírgula sete por cento.')
        self.assertEqual(narration_view(s),'probabilidade')
        with self.assertRaisesRegex(ValueError,'exige camada probabilidade'):
            validate_narration_layer(s)

    def test_percentage_requires_probability_even_without_word_probability(self):
        self.assertEqual(narration_view(self.scene('As chances chegam a 75,7%.')),'probabilidade')

    def test_count_requires_deterministic_map(self):
        self.assertEqual(narration_view(self.scene('A quantidade prevista de raios é de 500.',view='probabilidade')),'deterministico')

    def test_mixed_metrics_require_separate_scenes(self):
        with self.assertRaisesRegex(ValueError,'cenas separadas'):
            narration_view(self.scene('Probabilidade de 75% e acumulado de 500 raios.'))

    def test_qualitative_risk_and_observed_lightning_keep_their_layers(self):
        self.assertEqual(narration_view(self.scene('Risco alto de raios.',view='risco')),'risco')
        s=Segment('now','Agora','observacao','agora','monitoramento',narration='500 raios observados.')
        self.assertEqual(narration_view(s),'agora')

    def test_correct_scene_still_rejects_wrong_loaded_capture(self):
        s=self.scene('Probabilidade de 75%.',view='probabilidade');s.metadata={'view':'deterministico'}
        with self.assertRaisesRegex(ValueError,'imagem carregada'):
            validate_narration_layer(s)

    def test_accumulated_count_without_repeated_unit_is_not_a_percentage(self):
        self.assertEqual(narration_view(self.scene('O acumulado previsto é de 500.',view='probabilidade')),'deterministico')

    def test_spoken_count_requires_deterministic_map(self):
        self.assertEqual(narration_view(self.scene('São previstos mil raios.',view='probabilidade')),'deterministico')
