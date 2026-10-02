"""ThaiWater endpoint access and province-scoped raw response."""
from ..http import request


def fetch(url):
    return request(url, retry=True)


def scoped_payload(payload, province):
    # Preserve original fields for selected province; no renaming of raw records.
    if not province:
        return payload
    return {**payload, 'data': [row for row in payload['data']
            if isinstance(row, dict) and str((row.get('geocode') or {}).get('province_code')) == str(province)]}
