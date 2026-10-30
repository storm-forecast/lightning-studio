import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
import wave
from unittest.mock import patch
from lightning_video_engine.app.broadcast import compose

@unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'FFmpeg obrigatório')
class SceneTimingIntegration(unittest.TestCase):
    def test_map_changes_at_its_own_audio_boundary(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);maps=[]
            for i,color in enumerate((bytes([255,0,0]),bytes([0,0,255]))):
                image=root/f'{i}.ppm';image.write_bytes(b'P6\n64 64\n255\n'+color*4096);maps.append(image)
            audio=root/'audio.wav'
            with wave.open(str(audio),'wb') as w:
                w.setparams((1,2,16000,0,'NONE','not compressed'));w.writeframes(b'\0\0'*32000)
            with patch.dict(os.environ,{'NARRATION_SPEED':'1.0'}):
                compose(maps,audio,root/'test.mp4',title='Teste',subtitle='Teste',
                        timing_final=True,scene_durations=[.6,1.4])
            def pixel(t):
                return subprocess.check_output(['ffmpeg','-v','error','-ss',str(t),'-i',str(root/'test.mp4'),
                    '-vf','crop=2:2:900:300,scale=1:1','-frames:v','1','-pix_fmt','rgb24','-f','rawvideo','-'])
            red=pixel(.4);blue=pixel(.8)
            self.assertGreater(red[0],200);self.assertLess(red[2],30)
            self.assertGreater(blue[2],200);self.assertLess(blue[0],30)

    def test_rejects_timeline_that_does_not_match_audio(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);image=root/'map.ppm';image.write_bytes(b'P6\n2 2\n255\n'+bytes([0,0,0])*4)
            audio=root/'audio.wav'
            with wave.open(str(audio),'wb') as w:
                w.setparams((1,2,16000,0,'NONE','not compressed'));w.writeframes(b'\0\0'*16000)
            with self.assertRaisesRegex(ValueError,'não coincide'):
                compose([image],audio,root/'test.mp4',title='Teste',subtitle='Teste',
                        timing_final=True,scene_durations=[2])
