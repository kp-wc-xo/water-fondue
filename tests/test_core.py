import json
import tempfile
import unittest
from pathlib import Path
from datetime import datetime, timezone, timedelta
from unittest.mock import patch
from water_fondue.transform import normalize, timestamp, number, evaluate
from water_fondue.storage import SQLiteStore, SupabaseStore
from water_fondue.raw import archive, cleanup
from water_fondue.alerts import process_alerts, send_line

class Tests(unittest.TestCase):
    def setUp(self):
        self.payload = json.loads(Path('tests/fixtures/sample.json').read_text())
        self.s, self.o, _ = normalize(self.payload, '64')

    def test_timestamp(self):
        self.assertEqual(timestamp('2026-09-19 12:00'), '2026-09-19T05:00:00+00:00')

    def test_null(self):
        for v in (None, '', 'NaN', 'inf', 'bad'): self.assertIsNone(number(v))

    def test_filter(self):
        self.assertEqual(normalize(self.payload, '30')[1], [])

    def test_no_observation_id_fallback(self):
        self.payload['data'][0].pop('station'); self.payload['data'][0]['id'] = 100
        self.assertEqual(normalize(self.payload, '64')[2], 1)

    def test_bad_envelope(self):
        with self.assertRaises(ValueError): normalize({'result':'ERROR'}, '64')

    def test_duplicates(self):
        self.payload['data'] *= 2
        self.assertEqual(len(normalize(self.payload, '64')[1]), 1)

    def test_upsert_correction(self):
        with tempfile.TemporaryDirectory() as d:
            db=SQLiteStore(Path(d)/'test.sqlite')
            try:
                db.save(self.s,self.o); self.o[0]['level_msl']=45; db.save(self.s,self.o)
                self.assertEqual(len(db.latest()),1); self.assertEqual(db.latest()[0]['level_msl'],45)
                db.set_state('x',{'ok':True}); self.assertEqual(db.get_state('x'),{'ok':True})
            finally: db.close()

    def test_freshness(self):
        now=datetime.now(timezone.utc); row={**self.o[0], 'observed_at':now.isoformat()}
        self.assertEqual(evaluate(row,{'warning_msl':40},now,120,15),'warning')
        row['observed_at']=(now-timedelta(hours=3)).isoformat()
        self.assertIsNone(evaluate(row,{'warning_msl':40},now,120,15))
        row['observed_at']=(now+timedelta(hours=1)).isoformat()
        self.assertIsNone(evaluate(row,{'warning_msl':40},now,120,15))

    def test_raw_retention(self):
        with tempfile.TemporaryDirectory() as d:
            n,_=archive(self.payload,d); n2,_=archive(self.payload,d); self.assertEqual(n,n2)
            old='wf2_20000101_'+'a'*64+'.json.gz'; Path(d,old).write_bytes(b'test')
            Path(d,'keep.txt').write_text('keep')
            self.assertEqual(cleanup(d,7),[old]); self.assertTrue(Path(d,old).exists())
            cleanup(d,7,apply=True); self.assertFalse(Path(d,old).exists()); self.assertTrue(Path(d,'keep.txt').exists())

    def test_cloud_rpc(self):
        with patch.dict('os.environ',{'SUPABASE_URL':'https://example.invalid','SUPABASE_SERVICE_ROLE_KEY':'test'}):
            with patch('water_fondue.storage.request') as r:
                SupabaseStore().save(self.s,self.o)
                self.assertIn('/rpc/ingest_water',r.call_args.args[0])

    def test_line_quota(self):
        with patch.dict('os.environ',{'LINE_TARGET_ID':'Utest','LINE_CHANNEL_ACCESS_TOKEN':'test'}):
            with patch('water_fondue.alerts.request',side_effect=[{'value':200},{'totalUsage':50}]) as r:
                self.assertFalse(send_line('hello','key',50)); self.assertEqual(r.call_count,2)

    def test_alert_dedup(self):
        with tempfile.TemporaryDirectory() as d:
            db=SQLiteStore(Path(d)/'test.sqlite')
            row={**self.o[0],'observed_at':datetime.now(timezone.utc).isoformat()}
            cfg={'rules':{row['station_key']:{'warning_msl':40}},'stale_minutes':120,'max_future_minutes':15,'line_monthly_cap':50}
            try:
                with patch('water_fondue.alerts.send_line',return_value=True) as send:
                    process_alerts(db,[row],cfg,True); process_alerts(db,[row],cfg,True)
                    self.assertEqual(send.call_count,1)
            finally: db.close()

if __name__=='__main__': unittest.main()
