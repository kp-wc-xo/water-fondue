"""Private gzip snapshots; expiration only touches our filename namespace."""
import gzip
import hashlib
import json
import re
from datetime import datetime, timezone, timedelta
from pathlib import Path
from .http import request

PATTERN = re.compile(r'^wf2_\d{8}_[0-9a-f]{64}\.json\.gz$')


def archive(payload, root, cloud=None):
    """Canonicalize province-scoped API response, gzip and store content-addressed daily object.

    Byte-identical payloads on the same UTC day reuse the name. Raw is scoped to the selected province by the caller.
    Upstream changing ids/timestamps can still produce a new snapshot every poll.
    """
    body = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()
    name = 'wf2_' + datetime.now(timezone.utc).strftime('%Y%m%d') + '_' + hashlib.sha256(body).hexdigest() + '.json.gz'
    compressed = gzip.compress(body, mtime=0)
    if cloud:
        request(cloud.url + '/storage/v1/object/water-raw/' + name, 'POST', compressed,
                {**cloud.headers, 'Content-Type': 'application/gzip', 'x-upsert': 'true'}, retry=True)
    else:
        root = Path(root); root.mkdir(parents=True, exist_ok=True)
        (root / name).write_bytes(compressed)
    return name, len(compressed)


def cleanup(root, days, cloud=None, apply=False):
    """List managed snapshots; preview by default; delete older UTC dates when --apply.

    Cloud lists all pages before deletion so offsets cannot skip files during removal.
    No history table is touched; files outside wf2 naming pattern are never removed.
    """
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).strftime('%Y%m%d')
    if cloud:
        names, offset = [], 0
        while True:
            page = request(cloud.url + '/storage/v1/object/list/water-raw', 'POST',
                {'prefix': '', 'limit': 100, 'offset': offset, 'sortBy': {'column': 'name', 'order': 'asc'}},
                cloud.headers, retry=True)
            names.extend(r['name'] for r in page)
            if len(page) < 100: break
            offset += len(page)
    else:
        names = [p.name for p in Path(root).glob('wf2_*.json.gz')]
    expired = [n for n in names if PATTERN.fullmatch(n) and n[4:12] < cutoff]
    if apply:
        if cloud:
            for i in range(0, len(expired), 100):
                request(cloud.url + '/storage/v1/object/water-raw', 'DELETE',
                        {'prefixes': expired[i:i+100]}, cloud.headers, retry=True)
        else:
            for name in expired: (Path(root) / name).unlink()
    return expired
