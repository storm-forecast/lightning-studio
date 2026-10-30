from datetime import datetime,timezone
from zoneinfo import ZoneInfo
from pathlib import Path
import hashlib
import json
import tempfile
import unittest
from unittest.mock import patch
from lightning_video_engine.app.wardrobe import wardrobe_for_day,wardrobe_for_job
from lightning_video_engine.app.scheduling import interval_slot
from lightning_video_engine.app.job_store import JobStore

class WardrobeAndScheduleTests(unittest.TestCase):
    def catalog(self,root):
        variants=[]
        for i in range(10):
            f=root/f'{i}.mp4';f.write_bytes(bytes([i]));variants.append({'id':str(i),'name':str(i),
                'file':f.name,'sha256':hashlib.sha256(f.read_bytes()).hexdigest()})
        p=root/'catalogo.json';p.write_text(json.dumps({'timezone':'America/Belem','anchor_date':'2026-01-01','variants':variants}))
        return p

    def test_same_day_same_color_and_ten_distinct_days(self):
        with tempfile.TemporaryDirectory() as d:
            p=self.catalog(Path(d))
            days=[datetime(2026,1,i+1,12,tzinfo=timezone.utc) for i in range(10)]
            self.assertEqual(len({wardrobe_for_day(t,catalog_path=p)['id'] for t in days}),10)
            self.assertEqual(wardrobe_for_day(days[0],catalog_path=p)['id'],wardrobe_for_day(datetime(2026,1,1,23,tzinfo=timezone.utc),catalog_path=p)['id'])

    def test_changes_at_belem_midnight_not_utc_midnight(self):
        with tempfile.TemporaryDirectory() as d:
            p=self.catalog(Path(d))
            before=wardrobe_for_day(datetime(2026,10,31,2,59,tzinfo=timezone.utc),catalog_path=p)
            after=wardrobe_for_day(datetime(2026,10,31,3,tzinfo=timezone.utc),catalog_path=p)
            self.assertEqual(before['date'],'2026-10-30');self.assertEqual(after['date'],'2026-10-31')
            self.assertNotEqual(before['id'],after['id'])

    def test_job_keeps_recorded_outfit_when_resumed_next_day(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);p=self.catalog(root)
            choice=wardrobe_for_day(datetime(2026,1,1,12,tzinfo=timezone.utc),catalog_path=p)
            with patch('lightning_video_engine.app.wardrobe.wardrobe_for_day',return_value=choice):
                saved=wardrobe_for_job(root/'job')
            self.assertEqual(wardrobe_for_job(root/'job',datetime(2026,1,2,12,tzinfo=timezone.utc)),saved)

    def test_twelve_slots_a_day_and_no_duplicate_dispatch_after_restart(self):
        keys={interval_slot(datetime(2026,1,1,h,tzinfo=ZoneInfo('America/Belem')))[0] for h in range(24)}
        self.assertEqual(len(keys),12)
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'jobs.sqlite3';store=JobStore(path)
            self.assertTrue(store.add({'id':'first','state':'queued'},'slot')[1])
            resumed=JobStore(path)
            payload,inserted=resumed.add({'id':'second','state':'queued'},'slot')
            self.assertFalse(inserted);self.assertEqual(payload['id'],'first')

    def test_fails_if_color_video_was_modified(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);p=self.catalog(root);(root/'0.mp4').write_bytes(b'modified')
            with self.assertRaisesRegex(ValueError,'diferente do catálogo'):
                wardrobe_for_day(datetime(2026,1,1,12,tzinfo=timezone.utc),catalog_path=p)
