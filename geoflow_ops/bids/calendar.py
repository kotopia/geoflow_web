"""Read-only calendar projection of tenant bookmarks and source notice schedules."""
import json
from urllib.parse import urlencode

from django.db import connections
from django.urls import reverse
from django.utils import timezone

from procurement.models import Notice
from procurement.service import central_alias, enabled
from . import tenant_state
from .detail import presentation


def events(alias, actor, start, end):
    # Calendar callers must supply a bounded date range and enforce bids' view permission.
    if not start or not end or not 0 < (end - start).days <= 62:
        return []
    origin = 'central' if enabled(alias) else 'legacy'
    state = tenant_state.rows(alias, actor, origin)
    ids = [pk for pk, value in state.items() if value['saved'] and not value['hidden']]
    if not ids:
        return []
    if origin == 'central':
        notices = Notice.objects.using(central_alias()).filter(pk__in=ids).values(
            'id', 'number', 'title', 'source', 'posted_at', 'close_at', 'summary', 'raw').iterator()
    else:
        with connections[alias].cursor() as cur:
            cur.execute('SELECT id,bid_notice_no,title,posted_at,bid_close_at,open_at,notice_status,raw_payload FROM bid.notices WHERE id IN (' + ','.join(['%s'] * len(ids)) + ')', ids)
            notices = [dict(id=pk, number=number, title=title, source='g2b', posted_at=posted,
                close_at=close, summary={'open_at': opening, 'notice_status': status},
                raw=json.loads(raw) if isinstance(raw, str) else raw)
                for pk, number, title, posted, close, opening, status, raw in cur.fetchall()]
    progress = tenant_state.progress_rows(alias, actor, origin, ids)
    result = []
    for notice in notices:
        summary = dict(notice['summary'] or {}, source=notice['source'], posted_at=notice['posted_at'], bid_close_at=notice['close_at'])
        if summary.get('notice_status') == 'cancelled':
            continue
        normalized = presentation(summary, notice['raw'] or {})
        pk = str(notice['id'])
        current = progress.get(pk, {})
        for event in normalized['timeline']:
            key, at = event['key'], event['at']
            if key != 'open_at' or not at:
                continue
            at = timezone.localtime(at)
            if not start <= at.date() < end:
                continue
            result.append({
                'id': f'bid:{origin}:{pk}:{key}', 'title': notice['title'],
                'start': at.isoformat(), 'allDay': False,
                'url': reverse('tenant:bid_notice_list') + '?' + urlencode({'view': 'saved', 'closed': '1', 'q': notice['number'], 'notice': pk}),
                'extendedProps': {'scope_type': 'bid', 'scope_id': pk, 'scope_name': notice['title'],
                    'event_type': key, 'kind': '개찰 예정', 'history': False, 'stage': 'bidding',
                    'assignee': '미지정', 'progress_badge': current.get('progress_badge', '')},
            })
            if len(result) > 2000:
                raise ValueError('Calendar range exceeds 2000 events')
    return result
