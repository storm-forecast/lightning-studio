import unittest
from lightning_video_engine.app.segments import Segment
from lightning_video_engine.app.flood_narration import flood_places, flood_copy
from lightning_video_engine.app.editorial import validate_scene_evidence
from lightning_video_engine.app.production import fallback_narration


class FloodNarrationTests(unittest.TestCase):
    def scene(self):
        return Segment('07-alagamento','Alagamento','alagamento','inundacoes', evidence={
            'flood_references': {'areas':[
                {'id':'a','cidade_confirmada':True,'cidade':'Belém','estado':'Pará','pais':'Brasil'},
                {'id':'b','cidade_confirmada':False,'cidade':'Não confirmada','pais':'Brasil'}]}})

    def test_named_fallback_preserves_city_state_and_potential_only(self):
        s=self.scene();s.narration=fallback_narration(s,'31/10/2026')
        validate_scene_evidence(s)
        self.assertIn('região de Belém, Pará',s.narration)
        self.assertIn('não significa que todo o município',s.narration)
        self.assertEqual(flood_places(s), ['Belém, Pará'])

    def test_omitted_confirmed_city_is_rejected(self):
        s=self.scene();s.narration='O mapa apresenta potencial de alagamento.'
        with self.assertRaisesRegex(ValueError,'omitiu a cidade'):
            validate_scene_evidence(s)

    def test_no_mapping_requires_limitation_instead_of_invented_city(self):
        s=self.scene();s.evidence={};s.narration='Há risco na região de Cidade Inventada.'
        with self.assertRaises(ValueError):
            validate_scene_evidence(s)
        s.narration=fallback_narration(s,'31/10/2026')
        validate_scene_evidence(s)
        self.assertEqual(flood_copy(s),'')

    def test_severity_speaks_confirmed_destination_and_state(self):
        s=Segment('05-agora','Severidade','nowcasting','severidade', evidence={
            'flood_references':{'areas':[], 'locais_interesse':[
                {'cidade':'Salvador','estado':'Bahia','pais':'Brasil','dentro_poligono':True}]}})
        s.narration=fallback_narration(s,'31/10/2026')
        validate_scene_evidence(s)
        self.assertIn('região de Salvador, Bahia',s.narration)
        self.assertIn('severidade',s.narration)
        self.assertNotIn('alagamento',s.narration)
