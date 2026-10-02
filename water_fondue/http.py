"""Transport shared by ThaiWater, Supabase and LINE. Never log credentials."""
import json
import time
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError


def request(url, method='GET', data=None, headers=None, retry=False):
    """Serialize body; perform bounded HTTP; decode JSON. Retry only if caller marks safe."""
    headers = dict(headers or {})
    if data is not None and not isinstance(data, bytes):
        data = json.dumps(data, ensure_ascii=False).encode()
        headers.setdefault('Content-Type', 'application/json')
    headers.setdefault('User-Agent', 'WaterFondue/2.1')
    for attempt in range(3 if retry else 1):
        try:
            with urlopen(Request(url, data=data, headers=headers, method=method), timeout=45) as r:
                body = r.read()
                return json.loads(body) if body else None
        except HTTPError as exc:
            if exc.code == 409 and 'X-Line-Retry-Key' in headers:
                return {'already_accepted': True}
            if not retry or attempt == 2 or exc.code not in (429, 500, 502, 503, 504):
                # Do not include response body/URL: upstream may echo secrets.
                raise RuntimeError(f'HTTP request failed: status {exc.code}') from None
        except (URLError, TimeoutError):
            if not retry or attempt == 2:
                raise RuntimeError('HTTP connection failed or timed out') from None
        time.sleep(2 ** (attempt + 1))
