import os
from pathlib import Path
import shutil
import tempfile
import threading
import unittest
import wave
from unittest.mock import patch
from lightning_video_engine.app.segments import Segment
from lightning_video_engine.app.speech import prepare_scene_audio, prepare_scene_audios
from lightning_video_engine.app.official import render_official


def pcm(path):
    with wave.open(str(path), 'wb') as out:
        out.setparams((1, 2, 16000, 0, 'NONE', 'not compressed'))
        out.writeframes(b'\0\0' * 16000)


@unittest.skipUnless(shutil.which('ffmpeg'), 'FFmpeg required')
class AudioOptimizationTests(unittest.TestCase):
    def test_cache_tracks_text_and_rate_without_repeating_tts_for_rate_only(self):
        with tempfile.TemporaryDirectory() as folder:
            scene = Segment('scene', 'Teste', 'previsao', 'probabilidade', narration='Primeiro texto')
            def synth(text, path):
                pcm(path)
            with patch('lightning_video_engine.app.speech.narrate', side_effect=synth) as tts, patch.dict(os.environ, {'NARRATION_SPEED': '1.0'}):
                first = prepare_scene_audio(scene, folder)
                prepare_scene_audio(scene, folder)
                self.assertEqual(tts.call_count, 1)
                with patch.dict(os.environ, {'NARRATION_SPEED': '0.8'}):
                    prepare_scene_audio(scene, folder)
                    self.assertEqual(tts.call_count, 1)
                scene.narration = 'Segundo texto'
                prepare_scene_audio(scene, folder)
                self.assertEqual(tts.call_count, 2)
                self.assertTrue(Path(first).is_file())

    def test_parallel_audio_keeps_both_scenes_and_the_original_order(self):
        scenes = [Segment(str(i), 'Teste', 'previsao', 'probabilidade', narration=str(i)) for i in range(2)]
        barrier = threading.Barrier(2, timeout=5)
        def prepare(scene, directory):
            barrier.wait()
            return str(Path(directory) / (scene.id + '.wav'))
        with patch('lightning_video_engine.app.speech.prepare_scene_audio', side_effect=prepare):
            prepare_scene_audios(scenes, Path('/tmp'), workers=2)
        self.assertEqual([s.id for s in scenes], ['0', '1'])
        self.assertEqual([Path(s.audio).name for s in scenes], ['0.wav', '1.wav'])

    def test_final_pcm_is_passed_unchanged_to_sync_and_compositor(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            audio = root / 'audio.wav'; pcm(audio)
            python = root / 'python'; python.touch()
            model = root / 'model.pth'; model.touch()
            face = root / 'face.mp4'; face.touch()
            original = audio.read_bytes()
            with patch.dict(os.environ, {'LIPSYNC_PYTHON': str(python), 'WAV2LIP_CHECKPOINT': str(model)}), patch('lightning_video_engine.app.official.subprocess.run') as run, patch('lightning_video_engine.app.official.compose') as compose:
                render_official([], audio, root/'video.mp4', title='Teste', subtitle='Teste', narration_final=True, presenter_source=face)
            self.assertEqual(run.call_count, 2)  # face preparation + lip sync; no audio transcoding
            self.assertEqual(compose.call_args.args[1], audio.resolve())
            self.assertEqual(audio.read_bytes(), original)
