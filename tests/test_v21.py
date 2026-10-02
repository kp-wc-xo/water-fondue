import json
import os
import unittest
from unittest.mock import patch
from water_fondue.transform import normalize
from water_fondue.sources.thaiwater import scoped_payload
from water_fondue.storage import SupabaseStore

class CompatibilityTests(unittest.TestCase):
    def test_live_station_name_shape(self):
        payload={'data':[{'station':{'id':1,'tele_station_name':{'th':'บ้านทดสอบ'}},
          'geocode':{'province_code':'64','amphoe_code':'04'},'agency':{'id':9},
          'waterlevel_datetime':'2026-10-01 12:00','waterlevel_msl':'0'}]}
        s,o,bad=normalize(payload,'64')
        self.assertEqual(s[0]['name'],'บ้านทดสอบ')
        self.assertEqual(o[0]['level_msl'],0)
        self.assertEqual(s[0]['district_code'],'6404')
        self.assertEqual(bad,0)
    def test_scoped_raw(self):
        payload={'result':'OK','data':[{'geocode':{'province_code':'64'}},{'geocode':{'province_code':'30'}}]}
        self.assertEqual(len(scoped_payload(payload,'64')['data']),1)
        self.assertEqual(len(payload['data']),2)
    def test_new_key_not_sent_as_jwt(self):
        with patch.dict(os.environ,{'SUPABASE_URL':'https://example.invalid','SUPABASE_SECRET_KEY':'sb_secret_test'},clear=True):
            store=SupabaseStore()
            self.assertEqual(store.headers,{'apikey':'sb_secret_test'})
    def test_export_backup_roundtrip(self):
        import tempfile
        from pathlib import Path
        import gzip
        from water_fondue.storage import SQLiteStore
        from water_fondue.cli import export_backup
        with tempfile.TemporaryDirectory() as d:
            a=SQLiteStore(Path(d)/'a.sqlite'); b=SQLiteStore(Path(d)/'b.sqlite')
            payload=json.loads(Path('tests/fixtures/sample.json').read_text())
            s,o,_=normalize(payload,'64'); a.save(s,o)
            export_backup(a,Path(d)/'backup.gz')
            with gzip.open(Path(d)/'backup.gz','rt') as f:
                for line in f:
                    x=json.loads(line)
                    b.save([x['row']] if x['table']=='stations' else [],[x['row']] if x['table']=='observations' else [])
            self.assertEqual(a.latest(),b.latest())
            a.close(); b.close()
