import tempfile
import unittest
import wave
from pathlib import Path
from lightning_video_engine.app.segments import Segment, join_audio

class TimelineTests(unittest.TestCase):
    def test_different_speech_lengths_keep_different_scene_lengths(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);segments=[]
            for i,samples in enumerate((16001, 48000)):
                file=root/f'{i}.wav'
                with wave.open(str(file),'wb') as w:
                    w.setparams((1,2,16000,0,'NONE','not compressed'))
                    w.writeframes(b'\x00\x00'*samples)
                segments.append(Segment(str(i),'Teste','previsao','risco',audio=str(file)))
            total=join_audio(segments,root/'all.wav')
            self.assertEqual([s.duration for s in segments],[1.04,3.0])
            self.assertEqual(segments[1].start,segments[0].end)
            self.assertEqual(total,4.04)
            with wave.open(str(root/'all.wav')) as w:
                self.assertEqual(w.getnframes(),64640)

    def test_rejects_audio_with_wrong_sample_rate(self):
        with tempfile.TemporaryDirectory() as folder:
            file=Path(folder)/'audio.wav'
            with wave.open(str(file),'wb') as w:
                w.setparams((1,2,22050,0,'NONE','not compressed'));w.writeframes(b'\0\0'*22050)
            with self.assertRaises(ValueError):
                join_audio([Segment('a','a','previsao','risco',audio=str(file))],Path(folder)/'out.wav')

if __name__=='__main__':unittest.main()
