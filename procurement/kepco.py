"""KEPCO public bid adapter. POST secrets, bounded daily responses, no attachments fetched."""
import json
import re
from datetime import datetime, timedelta
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, build_opener, HTTPRedirectHandler

from django.conf import settings
from django.db.models import F
from django.utils.html import strip_tags
from django.utils import timezone
from geoflow_ops.bids.client import G2BError
from .client import Client
from .models import ApiBudget, Notice
from .policy import SEOUL, minute

ENDPOINT = 'https://bigdata.kepco.co.kr/openapi/v1/electContract.do'
MAX_RESPONSE = 20_000_000


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def industry_matches(term, row):
    # KEPCO does not expose a G2B license-code search. Match declared eligibility text,
    # never infer eligibility from a title, a delivery location, or a numeric G2B code.
    normalize = lambda s: re.sub(r'\s+', '', strip_tags(str(s or ''))).casefold()
    needle = normalize(term)
    return bool(needle) and needle in normalize(str(row.get('bidattendrestrict', '')) + ' ' + str(row.get('etc', '')))


def date_value(value):
    text = str(value or '').strip()
    if text in {'', '-'}:
        return ''
    for fmt in ('%Y%m%d%H%M%S', '%Y%m%d%H%M', '%Y%m%d', '%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M', '%Y-%m-%d'):
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=SEOUL).isoformat()
        except ValueError:
            pass
    raise G2BError('KEPCO_DATE_FORMAT', '한전 날짜 형식을 확인하세요.')


def adapt(item):
    row = {str(k).lower(): v for k, v in item.items()}
    if row.get('companyid') != 'COM01' or row.get('itemtype') != 'Service':
        return None
    if not row.get('no') or not row.get('name'):
        raise G2BError('KEPCO_NOTICE_KEY', '한전 공고 식별자를 확인하세요.')
    attachments = []
    for n in range(1, 6):
        url = str(row.get(f'filenlink{n}') or '')
        parsed = urlparse(url)
        if parsed.scheme in {'https', 'http'} and parsed.hostname in {'srm.kepco.net', 'srm.kepco.co.kr'}:
            attachments.append({'name': row.get(f'filename{n}') or '첨부파일', 'url': url})
    return dict(bidNtceNo=str(row['no']), bidNtceOrd='0', bidNtceNm=row['name'],
                bidNtceDt=date_value(row.get('noticedate')), bidClseDt=date_value(row.get('enddatetime')),
                bidBeginDt=date_value(row.get('begindatetime')), rgstDt=date_value(row.get('createdatetime')),
                ntceInsttNm='한국전력공사 ' + str(row.get('placename') or ''),
                dminsttNm=str(row.get('contractreqdepartmentname') or ''), presmptPrce=row.get('presumedprice'),
                _kepco=row, _attachments=attachments)


class KepcoClient(Client):
    def __init__(self, budget=100):
        super().__init__(budget)
        self.daily_cache = {}
        self.latest = []

    def day(self, day):
        key = str(getattr(settings, 'KEPCO_API_KEY', '')).strip()
        if not key:
            raise G2BError('KEPCO_MISSING_KEY', '한전 인증키 설정이 필요합니다.')
        if day in self.daily_cache:
            return self.daily_cache[day]
        if self.budget <= 0:
            raise G2BError('BUDGET_EXHAUSTED', '이번 작업의 호출 한도에 도달했습니다.')
        self.pace()
        self.reserve()
        self.budget -= 1
        request = Request(ENDPOINT, data=urlencode(dict(companyId='COM01', noticeBeginDate=day,
                          noticeEndDate=day, apiKey=key, returnType='json')).encode(), method='POST')
        try:
            with build_opener(NoRedirect).open(request, timeout=30) as response:
                raw = response.read(MAX_RESPONSE + 1)
        except HTTPError as exc:
            # The documented empty-result response is HTTP 404. All other HTTP errors
            # fail the window without advancing the cursor or exposing response text.
            if exc.code == 404:
                self.daily_cache[day] = []
                return []
            raise G2BError('KEPCO_HTTP_' + str(exc.code), '한전 API 응답 상태를 확인하세요.') from None
        except (URLError, TimeoutError, OSError):
            raise G2BError('KEPCO_NETWORK', '한전 API 연결에 실패했습니다.') from None
        if len(raw) > MAX_RESPONSE:
            raise G2BError('KEPCO_RESPONSE_LIMIT', '한전 일별 응답 크기 한도를 초과했습니다.')
        try:
            payload = json.loads(raw)
            rows = payload['data']
            if not isinstance(rows, list) or any(not isinstance(r, dict) for r in rows):
                raise ValueError()
        except (ValueError, KeyError, TypeError):
            raise G2BError('KEPCO_RESPONSE_FORMAT', '한전 응답 형식을 확인하세요.') from None
        ApiBudget.objects.using(getattr(settings, 'CENTRAL_DB_ALIAS', 'default')).filter(day=minute(timezone.now()).date()).update(received=F('received') + len(rows))
        # Bound the worker cache; a single window spans at most a few calendar days.
        if len(self.daily_cache) >= 4:
            self.daily_cache.pop(next(iter(self.daily_cache)))
        self.daily_cache[day] = rows
        return rows

    def search(self, rule, start, end):
        # Daily provider bounds are inclusive. Do not timestamp-filter a daily result:
        # corrections to earlier rows on that date must be upserted on every refresh.
        # Re-read the previous 30 posting days on incremental runs to catch corrections.
        live = bool(self.checkpoint and self.checkpoint.get('mode') == 'live')
        begin = (end - timedelta(days=30) if live else start).astimezone(SEOUL).date()
        finish = end.astimezone(SEOUL).date()
        known = set(Notice.objects.using(getattr(settings, "CENTRAL_DB_ALIAS", "default")).filter(source="kepco", rules=rule).values_list("number", flat=True))
        rows = []
        received = 0
        current = begin
        cache = self.checkpoint.setdefault('kepco_days', {}) if self.checkpoint is not None else {}
        while current <= finish:
            day = current.strftime('%Y%m%d')
            if day in cache:
                candidates, count = cache[day]['rows'], cache[day]['received']
            else:
                raw_rows = self.day(day)
                candidates = [adapt(r) for r in raw_rows]
                from .service import rule_matches
                candidates = [r for r in candidates if r is not None and (r["bidNtceNo"] in known or rule_matches(rule, r, {"industries": []}))]
                count = len(raw_rows)
                cache[day] = {'rows': candidates, 'received': count}
                self._save()
            rows.extend(candidates)
            received += count
            current += timedelta(days=1)
        if self.checkpoint is not None:
            self.checkpoint['provider_received'] = received
            self.checkpoint['provider'] = 'kepco'
            self._save()
        self.latest = rows
        return rows

    def changes(self, start, end):
        # search() already re-reads a rolling 30-day posting window. Older corrections
        # require an explicit backfill reset; the provider has no modified-since API.
        return []

    def details(self, row):
        return {'regions': [], 'industries': [], 'products': []}
