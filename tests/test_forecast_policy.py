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

    def test_lightning_copy_uses_plain_forecast_name(self):
        s=Segment('02-ecens','Raios','previsao','deterministico','ecens',narration='Previsão de Raios para o período indicado.')
        validate_forecast_text(s)
        s.narration='Raios previstos pelo modelo de inteligência artificial usando parâmetros convectivos do ECENS.'
        with self.assertRaisesRegex(ValueError, 'sem explicar o método'):
            validate_forecast_text(s)

    def test_probability_scene_rejects_rain_before_lightning(self):
        s=Segment('04-local-1','Raios','destaque','probabilidade','ecens',narration='A chuva será intensa. A probabilidade de raios é de 70%.')
        with self.assertRaisesRegex(ValueError, 'fala de chuva'):
            validate_forecast_text(s)
        s.narration='A probabilidade de raios é de 70% no período indicado.'
        validate_forecast_text(s)

    def test_lightning_fallback_matches_each_map_and_passes_policy(self):
        from lightning_video_engine.app.production import fallback_narration
        for view in ('probabilidade', 'deterministico', 'risco'):
            with self.subTest(view=view):
                s=Segment('04-local-1','Raios','destaque',view,'ecens')
                s.narration=fallback_narration(s, '31/10/2026')
                validate_forecast_text(s)
                self.assertEqual(narration_view(s), view)
                self.assertNotIn('chuva', s.narration.lower())

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


class ChannelNarrationTests(unittest.TestCase):
    def test_channel_name_occurs_once_across_scenes_and_resume(self):
        from lightning_video_engine.app.production import channel_narration, CLOSING_CTA
        opening=channel_narration('Bem-vindo ao Trovox Tempo. Previsão de Raios.', '02-ecens')
        closing=channel_narration('Acompanhe o TROVOX TEMPO. '+CLOSING_CTA, '11-recomendacoes')
        self.assertEqual((opening+' '+closing).casefold().count('trovox tempo'), 1)
        self.assertEqual(channel_narration(closing, '11-recomendacoes'), closing)
        self.assertIn('Previsão de Raios.', opening)
        self.assertTrue(closing.endswith(CLOSING_CTA))
