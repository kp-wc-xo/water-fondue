"""Opt-in single-recipient LINE push; durable transition state and provider quota guard."""
import os
import uuid
from datetime import datetime, timezone
from .http import request
from .transform import evaluate


def send_line(message, retry_key, cap):
    """Check OA quota + configured cap; send to ONE individual user ID, never a group.

    LINE provider consumption is authoritative; other senders can consume quota too.
    Retry key prevents duplicate accepted requests; pending older than 23h is blocked.
    """
    target = os.environ['LINE_TARGET_ID']
    if not target.startswith('U'):
        raise ValueError('Only individual LINE user ID allowed in free-budget mode')
    headers = {'Authorization': 'Bearer ' + os.environ['LINE_CHANNEL_ACCESS_TOKEN']}
    base = 'https://api.line.me/v2/bot/message/'
    quota = request(base + 'quota', headers=headers, retry=True)
    used = request(base + 'quota/consumption', headers=headers, retry=True)['totalUsage']
    limit = min(cap, quota.get('value', cap))
    if used >= limit:
        return False
    request(base + 'push', 'POST', {'to': target, 'messages': [{'type': 'text', 'text': message}]},
            {**headers, 'X-Line-Retry-Key': retry_key})
    return True


def process_alerts(store, observations, config, enabled=False):
    """Evaluate freshest row per station; first normal silent; warning/recovery on change.

    Dry notifier prints preview only and never changes alert state. Real notifier
    persists pending UUID before sending, then commits sent status. Stale data cannot
    trigger recovery. Pending ambiguous requests older than 23h require review.
    """
    now = datetime.now(timezone.utc)
    latest = {}
    for row in observations:
        key = row['station_key']
        if key not in latest or row['observed_at'] > latest[key]['observed_at']: latest[key] = row
    for key, row in latest.items():
        status = evaluate(row, config['rules'].get(key), now, config['stale_minutes'], config['max_future_minutes'])
        if status is None: continue
        state_key = 'alert:' + key
        old = store.get_state(state_key) or {'status': 'normal'}
        if old['status'] == status and not old.get('pending'): continue
        message = (f'[Water Fondue: experimental] {status}\n{key}\n'
                   f'Level {row["level_msl"]} m MSL\nObserved {row["observed_at"]}\n'
                   'Observed threshold only; not flood forecast or official warning.')
        if not enabled:
            print('LINE preview:', message); continue
        pending = old.get('pending')
        newly_pending = pending is None
        if pending:
            age = (now - datetime.fromisoformat(pending['created'])).total_seconds()
            if age > 23*3600 or pending['status'] != status:
                raise RuntimeError('Pending LINE event needs manual review; refusing duplicate/stale send')
        else:
            pending = {'key': str(uuid.uuid4()), 'created': now.isoformat(), 'status': status, 'message': message}
            store.set_state(state_key, {**old, 'pending': pending})
        if send_line(pending['message'], pending['key'], config['line_monthly_cap']):
            store.set_state(state_key, {'status': status, 'sent_at': now.isoformat()})
        else:
            if newly_pending:
                store.set_state(state_key, old)
            print('LINE quota guard: not sent')
