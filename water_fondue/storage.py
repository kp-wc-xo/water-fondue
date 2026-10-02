"""SQLite locally; Supabase REST/RPC in production. No key reaches the website."""
import json
import os
import sqlite3
from pathlib import Path
from urllib.parse import urlencode
from .http import request

SCHEMA = '''
CREATE TABLE IF NOT EXISTS stations(station_key TEXT PRIMARY KEY,name TEXT,province_code TEXT,district_code TEXT);
CREATE TABLE IF NOT EXISTS observations(station_key TEXT,observed_at TEXT,level_msl REAL,level_m REAL,situation REAL,
 PRIMARY KEY(station_key,observed_at));
CREATE TABLE IF NOT EXISTS state(key TEXT PRIMARY KEY,value TEXT);
'''


class SQLiteStore:
    """Context-managed persistent local database; separate from older v1 schema."""
    def __init__(self, path):
        """Create parents, connect and initialize schema; only non-dry-run paths call this."""
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.executescript(SCHEMA)

    def close(self):
        """Release file handle; required before copying backups on Windows."""
        self.db.close()

    def save(self, stations, observations):
        """Atomically upsert metadata and station/time observations, preserving source corrections."""
        with self.db:
            for s in stations:
                self.db.execute('INSERT OR REPLACE INTO stations VALUES(?,?,?,?)', tuple(s[k] for k in
                                ('station_key', 'name', 'province_code', 'district_code')))
            for o in observations:
                self.db.execute('INSERT OR REPLACE INTO observations VALUES(?,?,?,?,?)', tuple(o[k] for k in
                                ('station_key', 'observed_at', 'level_msl', 'level_m', 'situation')))

    def get_state(self, key):
        """Read private collector/alert state; return None if first run."""
        row = self.db.execute('SELECT value FROM state WHERE key=?', (key,)).fetchone()
        return json.loads(row[0]) if row else None

    def set_state(self, key, value):
        """Commit JSON state for durable retry/dedup between process executions."""
        with self.db:
            self.db.execute('INSERT OR REPLACE INTO state VALUES(?,?)', (key, json.dumps(value)))

    def latest(self):
        """Return latest observation per station for sanitized static website export."""
        self.db.row_factory = sqlite3.Row
        return [dict(r) for r in self.db.execute('''SELECT o.*,s.name,s.province_code FROM observations o
          JOIN stations s USING(station_key) WHERE o.observed_at=(SELECT MAX(x.observed_at)
          FROM observations x WHERE x.station_key=o.station_key) ORDER BY o.station_key''')]


class SupabaseStore:
    def __init__(self):
        """Load project URL and secret service-role JWT only from environment variables."""
        self.url = os.environ['SUPABASE_URL'].rstrip('/')
        if not self.url.startswith('https://'):
            raise ValueError('SUPABASE_URL must use HTTPS')
        key = os.environ.get('SUPABASE_SECRET_KEY') or os.environ.get('SUPABASE_SERVICE_ROLE_KEY')
        if not key:
            raise ValueError('Set SUPABASE_SECRET_KEY in the environment')
        if key.startswith('sb_publishable_'):
            raise ValueError('Use a backend secret key, not a publishable key')
        self.headers = {'apikey': key}
        if not key.startswith('sb_secret_'):
            self.headers['Authorization'] = 'Bearer ' + key

    def close(self):
        """REST adapter has no persistent local connection to close."""

    def save(self, stations, observations):
        """Call restricted SQL RPC: both upserts run in a single PostgreSQL transaction."""
        request(self.url + '/rest/v1/rpc/ingest_water', 'POST',
                {'p_stations': stations, 'p_observations': observations}, self.headers, retry=True)

    def get_state(self, key):
        """Fetch a single private state key through PostgREST."""
        query = urlencode({'key': 'eq.' + key, 'select': 'value'})
        rows = request(self.url + '/rest/v1/state?' + query, headers=self.headers, retry=True)
        return rows[0]['value'] if rows else None

    def set_state(self, key, value):
        """Upsert private state; merge on primary key for retries."""
        request(self.url + '/rest/v1/state', 'POST', {'key': key, 'value': value},
                {**self.headers, 'Prefer': 'resolution=merge-duplicates'}, retry=True)

    def latest(self):
        """Page through private latest view; service key stays inside the collector."""
        rows, offset = [], 0
        while True:
            query = urlencode({'select': '*', 'order': 'station_key', 'limit': 500, 'offset': offset})
            page = request(self.url + '/rest/v1/latest_water?' + query, headers=self.headers, retry=True)
            rows.extend(page)
            if len(page) < 500:
                return rows
            offset += len(page)
