import unittest
from lightning_video_engine.app.bulletin_context import spoken_brasilia, focus_on_available_regions, observed_precaution
from lightning_video_engine.app.segments import Segment


class NarrationClarityTests(unittest.TestCase):
    def test_only_brasilia_is_spoken_with_correct_previous_day(self):
        text=spoken_brasilia('2026-11-01T01:30:00Z')
        self.assertEqual(text,'31/10/2026 às 22:30, no horário de Brasília')
        self.assertNotIn('UTC',text)
        self.assertEqual(spoken_brasilia(text),text)

    def test_time_only_has_one_timezone(self):
        self.assertEqual(spoken_brasilia('15:00 UTC'),'12:00 no horário de Brasília')

    def test_missing_region_filler_is_removed_without_cutting_known_highlight(self):
        text='Há chuva prevista em Belém. Não há informações na região Sul. O Nordeste está sem dados.'
        self.assertEqual(focus_on_available_regions(text),'Há chuva prevista em Belém.')

    def test_observed_precaution_names_only_positive_brazilian_records(self):
        s=Segment('06-observado','Raios','observacao','agora',evidence={'observed':{'regioes':[
            {'cidade':'Belém','pais':'Brasil','raios':42}, {'cidade':'Recife','pais':'Brasil','raios':0}]}})
        copy=observed_precaution(s)
        self.assertIn('Belém',copy)
        self.assertNotIn('Recife',copy)
        self.assertIn('abrigo',copy)
