import importlib.util
import os
from datetime import datetime,timezone
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

@unittest.skipUnless(importlib.util.find_spec('fastapi'),'dependências da API não instaladas')
class JobDispatchIntegration(unittest.TestCase):
    def test_real_job_queue_survives_restart_without_duplicate_slots(self):
        with tempfile.TemporaryDirectory() as folder,patch.dict(os.environ,{
            'VIDEO_OUTPUT_DIR':folder,'VIDEO_INTERVAL_HOURS':'','VIDEO_DAILY_HOUR_UTC':''}),\
             patch('threading.Thread.start'):
            from lightning_video_engine.app import main
            with patch.object(main,'OUTPUT',Path(folder)):
                first=main.Jobs()
                agenda=main.IntervalScheduler(first,2,'America/Belem')
                now=datetime(2026,10,30,15,tzinfo=timezone.utc)
                a=agenda.tick(now);b=agenda.tick(now)
                self.assertEqual(a.id,b.id);self.assertEqual(first.queue.qsize(),1)
                a.state=main.State.rendering;first.persist(a)
                restarted=main.Jobs()
                self.assertEqual(restarted.items[a.id].state,main.State.queued)
                same=main.IntervalScheduler(restarted,2,'America/Belem').tick(now)
                self.assertEqual(same.id,a.id);self.assertEqual(restarted.queue.qsize(),1)
                following=main.IntervalScheduler(restarted,2,'America/Belem').tick(datetime(2026,10,30,17,tzinfo=timezone.utc))
                self.assertNotEqual(following.id,a.id);self.assertEqual(restarted.queue.qsize(),2)
