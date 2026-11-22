"""Read one public notice with tenant-owned notes; never fetch external files."""
import json
import re
from urllib.parse import parse_qsl, urlsplit

from django.db import connections
from django.http import Http404

from procurement.service import central_alias, enabled
from .sync import _date

SENSITIVE = {'apikey', 'servicekey', 'accesskey', 'accesstoken', 'authorization', 'password', 'secret', 'token'}
LABELS = {
    'notice': '공고', 'regions': '참가가능지역', 'industries': '업종·면허',
    'basis_amount': '기초금액', 'products': '품목', '_kepco': '한전 원문',
    'bidNtceNo': '공고번호', 'bidNtceOrd': '공고차수', 'bidNtceNm': '공고명',
    'bidNtceDt': '게시일', 'bidClseDt': '투찰 마감', 'bidBeginDt': '투찰 시작',
    'opengDt': '개찰일', 'bidQlfctRgstDt': '참가등록 마감', 'ntceInsttNm': '발주기관',
    'dminsttNm': '수요기관', 'presmptPrce': '추정가격', 'bssamt': '기초금액',
    'cntrctCnclsMthdNm': '계약방법', 'bidMethdNm': '입찰방법', 'sucsfbidMthdNm': '낙찰방법',
    'ntceInsttOfclNm': '담당자', 'ntceInsttOfclTelNo': '담당자 연락처',
    'ntceInsttOfclEmailAdrs': '담당자 이메일', 'prtcptPsblRgnNm': '참가가능지역',
    'lcnsLmtNm': '업종·면허 제한', 'bidNtceDtlUrl': '공고 원문 주소',
    'name': '공고명', 'no': '공고번호', 'noticedate': '게시일', 'enddatetime': '투찰 마감',
    'begindatetime': '투찰 시작', 'bidattendrestrict': '참가자격', 'placename': '발주부서',
    'contractreqdepartmentname': '수요부서', 'etc': '기타 안내', 'progressstate': '진행상태',
}


def sensitive(key):
    return re.sub(r'[^a-z]', '', str(key).lower()) in SENSITIVE


def safe_url(value, source):
    if not isinstance(value, str):
        return None
    try:
        parsed = urlsplit(value.strip())
        domains = ('kepco.co.kr', 'kepco.net') if source == 'kepco' else ('g2b.go.kr',)
        host = (parsed.hostname or '').lower()
        if (parsed.scheme not in {'https', 'http'} or parsed.username or parsed.password
                or any(sensitive(key) for key, _ in parse_qsl(parsed.query))
                or not any(host == d or host.endswith('.' + d) for d in domains)):
            return None
    except ValueError:
        return None
    return value.strip()


def public_payload(value):
    if isinstance(value, dict):
        return {key: public_payload(item) for key, item in value.items() if not sensitive(key)}
    if isinstance(value, list):
        return [public_payload(item) for item in value]
    if isinstance(value, str) and value.startswith(('http://', 'https://')):
        try:
            parsed = urlsplit(value)
            if parsed.username or parsed.password or any(sensitive(k) for k, _ in parse_qsl(parsed.query)):
                return '(인증정보가 포함된 주소 생략)'
        except ValueError:
            return '(잘못된 주소)'
    return value


def fields(value, path=''):
    if isinstance(value, dict) and value:
        for key, item in value.items():
            label = LABELS.get(key, key)
            yield from fields(item, f'{path} / {label}' if path else str(label))
    elif isinstance(value, list) and value:
        for index, item in enumerate(value, 1):
            yield from fields(item, f'{path} [{index}]')
    else:
        text = '미제공' if value is None or value == '' else (json.dumps(value, ensure_ascii=False) if isinstance(value, (list,dict,bool)) else str(value))
        yield dict(label=path or '값', value=text)


def attachment_links(raw, summary, source):
    found = {}
    def add(url, name):
        url = safe_url(url, source)
        if url:
            found.setdefault(url, dict(url=url, name=str(name or '첨부파일')))
    def visit(value):
        if isinstance(value, dict):
            lower = {str(k).lower(): v for k,v in value.items()}
            for key, url in lower.items():
                match = re.fullmatch(r'ntcespecdocurl(\d+)', key)
                if match:
                    add(url, lower.get('ntcespecfilenm' + match[1]))
                match = re.fullmatch(r'filenlink(\d+)', key)
                if match:
                    add(url, lower.get('filename' + match[1]))
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)
    visit(raw)
    for item in summary.get('attachments') or []:
        if isinstance(item, dict):
            add(item.get('url'), item.get('name'))
    return list(found.values())


def load(alias, notice_id, *, history=False):
    central = enabled(alias)
    if central and not history:
        from procurement.models import Notice
        obj = Notice.objects.using(central_alias()).filter(pk=notice_id).first()
        if obj is None:
            raise Http404('공고를 찾을 수 없습니다.')
        summary = dict(obj.summary, id=str(obj.pk), title=obj.title, posted_at=obj.posted_at,
                       bid_close_at=obj.close_at, source=obj.source, region_text=obj.region_text,
                       industry_text=obj.industry_text, bid_notice_no=obj.number, bid_notice_ord=obj.order,
                       notice_agency_name=obj.agency, demand_agency_name=obj.demand_agency,
                       estimated_price=obj.estimated_price)
        raw = obj.raw
        with connections[alias].cursor() as cur:
            cur.execute('SELECT memo,status FROM bid.central_reviews WHERE central_notice_id=%s', [str(notice_id)])
            review = cur.fetchone()
        summary['memo'] = (review[0] or '') if review else ''
        summary['review_status'] = review[1] if review else ''
    else:
        with connections[alias].cursor() as cur:
            cur.execute('SELECT n.*,COALESCE(r.memo,\'\') AS memo,r.status AS review_status FROM bid.notices n LEFT JOIN bid.notice_reviews r ON r.notice_id=n.id WHERE n.id=%s', [str(notice_id)])
            row = cur.fetchone()
            if row is None:
                raise Http404('공고를 찾을 수 없습니다.')
            summary = dict(zip([col[0] for col in cur.description], row))
        summary['id'] = str(summary['id'])
        summary['source'] = 'g2b'
        raw = summary.pop('raw_payload', {})
        if isinstance(raw, str):
            raw = json.loads(raw)
    raw = public_payload(raw)
    source = summary['source']
    summary['source_label'] = '한국전력' if source == 'kepco' else '나라장터'
    for key in ('posted_at', 'bid_close_at', 'open_at', 'bid_begin_at', 'registration_close_at'):
        if not hasattr(summary.get(key), 'strftime'):
            try:
                summary[key] = _date(summary.get(key))
            except (ValueError, TypeError):
                summary[key] = None
    url = safe_url(summary.get('detail_url'), source)
    summary['original_is_search'] = not bool(url)
    summary['original_url'] = url or ('https://srm.kepco.net/' if source == 'kepco' else 'https://www.g2b.go.kr/')
    summary['attachments'] = attachment_links(raw, summary, source)
    summary['collected_fields'] = list(fields(raw))
    return summary
