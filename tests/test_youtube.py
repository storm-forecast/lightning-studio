import importlib.util
import io
import os
import json
import tempfile
import unittest
import urllib.error
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch

from lightning_video_engine.app import youtube

ENV = {'YOUTUBE_CLIENT_ID': 'id', 'YOUTUBE_CLIENT_SECRET': 'secret', 'YOUTUBE_REFRESH_TOKEN': 'refresh',
       'YOUTUBE_CHANNEL_ID': 'UCOrGMudYslWWWmpW8pu3UDg'}
AT = datetime(2026, 10, 31, 17, 17, tzinfo=timezone.utc)


def http_error(reason):
    body = json.dumps({'error': {'errors': [{'reason': reason}]}}).encode()
    return urllib.error.HTTPError('https://x', 403, 'Forbidden', {}, io.BytesIO(body))


class Metadata(unittest.TestCase):
    def test_title_uses_belem_time_and_description_lists_highlights(self):
        with tempfile.TemporaryDirectory() as folder:
            Path(folder, 'destaques-ecens.json').write_text(json.dumps({'brasil_maior_atividade_raios': [
                {'cidade': 'Manaus', 'pais': 'Brasil'}, {'cidade': 'Belém', 'pais': 'Brasil'}]}))
            meta = youtube.bulletin_metadata(Path(folder), AT)
        self.assertIn('31/10/2026 às 14h', meta['snippet']['title'])
        self.assertLessEqual(len(meta['snippet']['title']), 100)
        self.assertIn('Manaus (Brasil), Belém (Brasil)', meta['snippet']['description'])
        self.assertEqual(meta['status'], {'privacyStatus': 'private', 'selfDeclaredMadeForKids': False,
                                          'containsSyntheticMedia': True})

    def test_missing_highlights_and_invalid_privacy(self):
        with tempfile.TemporaryDirectory() as folder:
            self.assertNotIn('Destaques', youtube.bulletin_metadata(Path(folder), AT)['snippet']['description'])
            with self.assertRaises(ValueError):
                youtube.bulletin_metadata(Path(folder), AT, privacy='publico')

    def test_scheduled_publish_is_private_until_the_requested_instant(self):
        publish_at = datetime(2026, 11, 1, 12, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as folder:
            meta = youtube.bulletin_metadata(Path(folder), AT, privacy='public', publish_at=publish_at)
        self.assertEqual(meta['status']['privacyStatus'], 'private')
        self.assertEqual(meta['status']['publishAt'], '2026-11-01T12:00:00Z')


class Publish(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.directory = Path(self.folder.name)
        (self.directory / 'boletim.mp4').write_bytes(b'mp4')

    def tearDown(self):
        self.folder.cleanup()

    def test_refuses_token_from_another_channel(self):
        with patch.object(youtube, 'access_token', return_value='t'), \
             patch.object(youtube, 'authorized_channel', return_value=('UCoutro', 'Outro')), \
             patch.object(youtube, 'upload') as upload:
            with self.assertRaisesRegex(youtube.YouTubeError, 'UCoutro'):
                youtube.publish_bulletin(self.directory, AT, ENV)
        upload.assert_not_called()

    def test_records_uploaded_video(self):
        with patch.object(youtube, 'access_token', return_value='t'), \
             patch.object(youtube, 'authorized_channel', return_value=(ENV['YOUTUBE_CHANNEL_ID'], 'Canal')), \
             patch.object(youtube, 'upload', return_value={'id': 'abc', 'status': {'privacyStatus': 'private'}}):
            record = youtube.publish_bulletin(self.directory, AT, ENV)
        self.assertEqual(record['url'], 'https://youtu.be/abc')
        self.assertEqual(json.loads((self.directory / 'youtube.json').read_text())['video_id'], 'abc')

    def test_records_scheduled_publication(self):
        publish_at = datetime.now(timezone.utc) + timedelta(hours=2)
        stamp = publish_at.isoformat().replace('+00:00', 'Z')
        with patch.object(youtube, 'access_token', return_value='t'), \
             patch.object(youtube, 'authorized_channel', return_value=(ENV['YOUTUBE_CHANNEL_ID'], 'Canal')), \
             patch.object(youtube, 'upload', return_value={'id': 'abc', 'status': {'privacyStatus': 'private'}}) as upload:
            record = youtube.publish_bulletin(self.directory, AT, ENV, publish_at=publish_at)
        self.assertEqual(record['scheduled_publish_at'], stamp)
        self.assertEqual(upload.call_args.args[1]['status']['publishAt'], stamp)

    def test_late_scheduled_bulletin_is_uploaded_publicly(self):
        with patch.object(youtube, 'access_token', return_value='t'), \
             patch.object(youtube, 'authorized_channel', return_value=(ENV['YOUTUBE_CHANNEL_ID'], 'Canal')), \
             patch.object(youtube, 'upload', return_value={'id': 'abc', 'status': {'privacyStatus': 'public'}}) as upload:
            record = youtube.publish_bulletin(self.directory, AT, {**ENV, 'YOUTUBE_PRIVACY': 'public'},
                                              publish_at=datetime.now(timezone.utc)-timedelta(minutes=1))
        self.assertEqual(record['privacy'], 'public')
        self.assertNotIn('publishAt', upload.call_args.args[1]['status'])

    def test_upload_must_confirm_public_visibility(self):
        with patch.object(youtube, 'access_token', return_value='t'), \
             patch.object(youtube, 'authorized_channel', return_value=(ENV['YOUTUBE_CHANNEL_ID'], 'Canal')), \
             patch.object(youtube, 'upload', return_value={'id': 'abc', 'status': {'privacyStatus': 'private'}}):
            with self.assertRaisesRegex(youtube.YouTubeError, 'privacidade'):
                youtube.publish_bulletin(self.directory, AT, {**ENV, 'YOUTUBE_PRIVACY': 'public'})

    def test_missing_secrets_are_named(self):
        with self.assertRaisesRegex(youtube.YouTubeError, 'YOUTUBE_REFRESH_TOKEN'):
            youtube.publish_bulletin(self.directory, AT, {**ENV, 'YOUTUBE_REFRESH_TOKEN': ''})

    def test_quota_errors_are_distinguished(self):
        with patch('urllib.request.urlopen', side_effect=http_error('quotaExceeded')):
            with self.assertRaises(youtube.QuotaExceeded):
                youtube.access_token('id', 'secret', 'refresh')
        with patch('urllib.request.urlopen', side_effect=http_error('forbidden')):
            with self.assertRaises(youtube.YouTubeError) as caught:
                youtube.access_token('id', 'secret', 'refresh')
            self.assertNotIsInstance(caught.exception, youtube.QuotaExceeded)


@unittest.skipUnless(importlib.util.find_spec('fastapi'), 'dependências da API não instaladas')
class RenderWorker(unittest.TestCase):
    def test_upload_failure_is_recorded_without_failing_job(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {'VIDEO_OUTPUT_DIR': folder}), \
             patch('threading.Thread.start'):
            from lightning_video_engine.app import main
            job = main.Job(id='j', request=main.VideoRequest(titulo='Boletim'), output=f'{folder}/j/boletim.mp4')
            with patch.dict(os.environ, {'YOUTUBE_REFRESH_TOKEN': ''}):
                self.assertIsNone(main.publish(job))
            with patch.dict(os.environ, {'YOUTUBE_REFRESH_TOKEN': 'r'}), \
                 patch.object(main, 'publish_bulletin', side_effect=youtube.QuotaExceeded('cota')):
                self.assertEqual(main.publish(job), {'error': 'cota', 'quota': True})


if __name__ == '__main__':
    unittest.main()
