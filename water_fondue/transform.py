"""Pure functions. This module never writes files, contacts APIs or sends LINE."""
import math
from datetime import datetime, timezone, timedelta


def timestamp(value):
    """Parse source time; naive timestamps mean ICT; return canonical UTC ISO text."""
    dt = datetime.fromisoformat(str(value).replace('/', '-').replace('Z', '+00:00'))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone(timedelta(hours=7)))
    return dt.astimezone(timezone.utc).isoformat()


def number(value):
    """Keep missing/malformed/non-finite values NULL, never replace them with zero."""
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (ValueError, TypeError):
        return None


def normalize(payload, province):
    """Validate envelope; filter province; split station metadata from narrow observations.

    Stable key uses agency plus station.id, NOT the observation's top-level id.
    Unknown/malformed station/time records are counted and skipped. Duplicates within
    a response use the last record. Units remain source m MSL and m; no conversion.
    """
    if not isinstance(payload, dict) or payload.get('result') not in (None, 'OK'):
        raise ValueError('Invalid API envelope/result')
    rows = payload.get('data')
    if not isinstance(rows, list):
        raise ValueError('Expected data array')
    stations, observations, rejected = {}, {}, 0
    for row in rows:
        try:
            geo = row.get('geocode') or {}
            if province and str(geo.get('province_code')) != province:
                continue
            station = next((row[k] for k in ('station', 'tele_station', 'waterlevel_station')
                            if isinstance(row.get(k), dict) and row[k].get('id') is not None), None)
            if station is None:
                raise ValueError('Missing stable station id')
            agency = (row.get('agency') or {}).get('id', '')
            key = f'thaiwater:waterlevel:{agency}:{station["id"]}'
            observed = timestamp(row['waterlevel_datetime'])
            name = (station.get('tele_station_name') or station.get('name')
                    or station.get('station_name') or str(station['id']))
            if isinstance(name, dict):
                name = name.get('th') or name.get('en') or str(station['id'])
            pc, ac = str(geo.get('province_code', '')), str(geo.get('amphoe_code', ''))
            district = pc + ac if len(pc) == len(ac) == 2 and (pc + ac).isdigit() else None
            stations[key] = dict(station_key=key, name=str(name), province_code=pc,
                                 district_code=district)
            observations[(key, observed)] = dict(station_key=key, observed_at=observed,
                level_msl=number(row.get('waterlevel_msl')), level_m=number(row.get('waterlevel_m')),
                situation=number(row.get('situation_level')))
        except (ValueError, TypeError, KeyError, AttributeError):
            rejected += 1
    return list(stations.values()), list(observations.values()), rejected


def evaluate(observation, rule, now, stale_minutes, max_future_minutes):
    """Return warning/normal only for fresh valid MSL data and explicit station threshold.

    Threshold is a user-approved MSL level, NOT a prediction or universal bank level.
    Stale, future, missing and unconfigured values yield None and never recovery.
    """
    if not rule or observation['level_msl'] is None:
        return None
    threshold = number(rule.get('warning_msl'))
    if threshold is None:
        return None
    age = (now - datetime.fromisoformat(observation['observed_at'])).total_seconds() / 60
    if age > stale_minutes or age < -max_future_minutes:
        return None
    return 'warning' if observation['level_msl'] >= threshold else 'normal'
