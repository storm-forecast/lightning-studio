import unittest
from lightning_video_engine.app.segments import Segment
from lightning_video_engine.app.tourism import tourism_evidence, tourism_direction


class TourismTests(unittest.TestCase):
    def test_rain_does_not_borrow_lightning_evidence(self):
        s=Segment('01-chuva','Chuva','previsao','chuva-prevista', evidence={'editorial': {
            'chuva': {'regioes': [{'cidade':'Recife','pais':'Brasil'}]},
            'raios': {'regioes': [{'cidade':'Manaus','pais':'Brasil'}]}}})
        self.assertEqual([x['cidade'] for x in tourism_evidence(s)], ['Recife'])
        self.assertNotIn('Manaus', tourism_direction(s))

    def test_zero_observations_and_foreign_places_are_not_highlights(self):
        s=Segment('06-observado','Raios','observacao','agora', evidence={'observed': {'regioes':[
            {'cidade':'Natal','pais':'Brasil','raios':0},
            {'cidade':'Belém','pais':'Brasil','raios':25},
            {'cidade':'Salvador','pais':'Outro','raios':99}]}})
        self.assertEqual([x['cidade'] for x in tourism_evidence(s)], ['Belém'])

    def test_bonito_needs_state_confirmation(self):
        s=Segment('02-ecens','Raios','previsao','deterministico',evidence={'editorial':{
            'raios':{'regioes':[{'cidade':'Bonito','pais':'Brasil'}]}}})
        self.assertEqual(tourism_evidence(s), [])
        s.evidence['editorial']['raios']['regioes'][0]['uf']='MS'
        self.assertEqual(tourism_evidence(s)[0]['cidade'], 'Bonito')

    def test_polygons_without_city_associations_cannot_locate_a_destination(self):
        s=Segment('05-agora','Agora','nowcasting','severidade',metadata={'polygon_count':8})
        self.assertEqual(tourism_evidence(s), [])
        self.assertEqual(tourism_direction(s), '')
