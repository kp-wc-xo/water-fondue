"""One entry point, shared transforms, explicitly selected side effects."""
import argparse
import gzip
import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode
from .http import request
from .transform import normalize
from .storage import SQLiteStore, SupabaseStore
from .raw import archive, cleanup
from .alerts import process_alerts
from .sources.thaiwater import fetch, scoped_payload


def export_backup(store, target):
    """Stream all observations to gzip JSONL for archival; does NOT delete database rows.

    Run while ingestion paused for a consistent cross-page cloud backup. Station
    metadata is written first; state contains private IDs so is intentionally excluded.
    """
    target = Path(target); target.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(target, 'wt', encoding='utf-8') as stream:
        for table in ('stations', 'observations'):
            if isinstance(store, SQLiteStore):
                import sqlite3
                store.db.row_factory = sqlite3.Row
                # Table names are fixed constants, never user input.
                for row in store.db.execute('SELECT * FROM ' + table):
                    stream.write(json.dumps({'table': table, 'row': dict(row)}, ensure_ascii=False) + '\n')
            else:
                offset = 0
                while True:
                    order = 'station_key,observed_at' if table == 'observations' else 'station_key'
                    q = urlencode({'select': '*', 'order': order, 'limit': 500, 'offset': offset})
                    page = request(store.url + '/rest/v1/' + table + '?' + q, headers=store.headers, retry=True)
                    for row in page: stream.write(json.dumps({'table': table, 'row': row}, ensure_ascii=False) + '\n')
                    if len(page) < 500: break
                    offset += len(page)


def main():
    """Parse commands/config; dry-run before opening storage; close connections in finally.

    collect=fetch+archive+normalize+upsert+optional alert; export=public latest;
    cleanup=raw only; backup=lossless station/observation archive; restore=local only.
    """
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('command', choices=['collect', 'export', 'cleanup', 'backup', 'restore'])
    p.add_argument('--profile', choices=['local', 'test', 'production'], default='local')
    p.add_argument('--config', default='config.json'); p.add_argument('--input')
    p.add_argument('--dry-run', action='store_true'); p.add_argument('--apply', action='store_true')
    p.add_argument('--send-line', action='store_true'); p.add_argument('--output', default='site/data.json')
    a = p.parse_args()
    config = json.loads(Path(a.config).read_text(encoding='utf-8'))
    if config['raw_days'] not in (7, 15): p.error('raw_days must be 7 or 15')
    if a.profile == 'test' and a.command == 'collect' and not a.input: p.error('test requires --input fixture')
    if a.profile == 'production' and a.input: p.error('Never import fixture into production')
    if a.send_line and (a.profile != 'production' or not config['line_enabled']):
        p.error('Sending requires production profile AND line_enabled=true')
    if a.command == 'restore' and (a.profile == 'production' or not a.input):
        p.error('restore requires --input gzip archive and local/test profile')
    payload = None
    if a.command == 'collect':
        payload = json.loads(Path(a.input).read_text(encoding='utf-8')) if a.input else fetch(config['source_url'])
        stations, observations, rejected = normalize(payload, config['province'])
        print(json.dumps({'stations': len(stations), 'observations': len(observations), 'rejected': rejected}))
        if not observations: raise ValueError('No valid observations: previous data preserved; inspect source/filter')
    if a.dry_run:
        print('DRY RUN: no database, raw, export, deletion or LINE side effects'); return
    root = Path('data') / a.profile
    store = SupabaseStore() if a.profile == 'production' else SQLiteStore(root / 'water_fondue_v2.sqlite')
    try:
        cloud = store if a.profile == 'production' else None
        if a.command == 'collect':
            archive(scoped_payload(payload, config['province']), root / 'raw', cloud)
            store.save(stations, observations)
            store.set_state('last_success', {'at': datetime.now(timezone.utc).isoformat(), 'rejected': rejected})
            process_alerts(store, observations, config, a.send_line)
        elif a.command == 'cleanup':
            names = cleanup(root / 'raw', config['raw_days'], cloud, a.apply)
            print(('Deleted' if a.apply else 'Would delete'), len(names), 'managed raw files')
        elif a.command == 'export':
            target = Path(a.output); target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(json.dumps({'generated_at': datetime.now(timezone.utc).isoformat(),
                'ingestion': store.get_state('last_success'), 'profile': a.profile,
                'stale_minutes': config['stale_minutes'], 'max_future_minutes': config['max_future_minutes'],
                'rows': store.latest()}, ensure_ascii=False), encoding='utf-8')
        elif a.command == 'backup':
            export_backup(store, a.output)
        elif a.command == 'restore':
            # Bounded batches; metadata lines precede observations in our archive.
            with gzip.open(a.input, 'rt', encoding='utf-8') as stream:
                for line in stream:
                    entry = json.loads(line)
                    if entry['table'] == 'stations': store.save([entry['row']], [])
                    elif entry['table'] == 'observations': store.save([], [entry['row']])
                    else: raise ValueError('Unknown backup table')
    finally:
        store.close()
