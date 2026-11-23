"""Read one public notice with tenant-owned notes; never fetch external files."""
import json
import re
from urllib.parse import parse_qsl, urlsplit

from django.db import connections
from django.http import Http404
from django.utils import formats, timezone

from procurement.service import central_alias, enabled
from .sync import _date, _money

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


def presentation(summary, raw, *, now=None):
    """One display contract for both providers; never invent missing eligibility/results."""
    now = now or timezone.now()
    row = raw.get('notice', {}) if isinstance(raw, dict) else {}
    row = row if isinstance(row, dict) else {}
    if summary.get('source') == 'g2b':
        for field, key in {
            'award_method_name': 'sucsfbidMthdNm',
            'registration_close_at': 'bidQlfctRgstDt',
            'joint_contract_method': 'cmmnSpldmdMethdNm',
            'vat_amount': 'VAT',
        }.items():
            if summary.get(field) in (None, ''):
                summary[field] = row.get(key)
    # KEPCO eligibility stays provider text. Do not parse it into G2B license codes,
    # infer province restrictions from the agency, or invent an opening date.
    for key in ('posted_at', 'bid_close_at', 'open_at', 'bid_begin_at', 'registration_close_at'):
        try:
            summary[key] = _date(summary.get(key))
        except (ValueError, TypeError):
            summary[key] = None

    def text(value):
        return str(value) if value not in (None, '') else '미제공'

    def money(key):
        value = _money(summary.get(key))
        return formats.number_format(value, decimal_pos=0, use_l10n=True, force_grouping=True) + '원' if value is not None else '미제공'

    def date(key):
        value = summary.get(key)
        return timezone.localtime(value).strftime('%Y.%m.%d %H:%M') if value else '미제공'

    def row_values(*pairs):
        return [{'label': label, 'value': value} for label, value in pairs]

    summary['sections'] = [
        dict(id='general', title='공고일반', rows=[
            row_values(('발주기관', text(summary.get('notice_agency_name'))), ('수요기관', text(summary.get('demand_agency_name')))),
            row_values(('업무구분', {'service': '용역'}.get(summary.get('business_type', 'service'), '미제공')), ('계약방법', text(summary.get('contract_method_name')))),
            row_values(('입찰방법', text(summary.get('bid_method_name'))), ('낙찰방법', text(summary.get('award_method_name')))),
            row_values(('게시일', date('posted_at')), ('개찰 예정', date('open_at'))),
        ]),
        dict(id='eligibility', title='참가자격', rows=[
            row_values(('참가가능지역', text(summary.get('region_text')))),
            row_values(('업종·면허', text(summary.get('industry_text')))),
            row_values(('공동수급', text(summary.get('joint_contract_method')))),
            row_values(('참가자격 원문', text(summary.get('qualification_text')))),
        ]),
        dict(id='amounts', title='금액', rows=[
            row_values(('기초금액', money('basic_amount')), ('추정가격', money('estimated_price'))),
            row_values(('부가가치세', money('vat_amount')), ('사업예산', money('budget_amount'))),
        ]),
    ]
    cancelled = summary.get('notice_status') == 'cancelled'
    cutoff = summary.get('bid_close_at') or summary.get('open_at')
    start = summary.get('bid_begin_at')
    if cancelled:
        state = ('취소', 'secondary')
    elif summary.get('notice_status') == 'closed' or (cutoff and cutoff <= now):
        state = ('마감', 'secondary')
    elif start and start > now:
        state = ('접수 예정', 'secondary')
    elif start and summary.get('bid_close_at') and start <= now < summary['bid_close_at']:
        state = ('접수 중', 'primary')
    else:
        state = ('일정 확인 필요', 'secondary')
    summary['schedule_label'], summary['schedule_color'] = state
    summary['timeline'] = []
    for key, label in [('posted_at', '공고 게시'), ('bid_begin_at', '접수 시작'),
                       ('registration_close_at', '참가등록 마감'), ('bid_close_at', '투찰 마감'), ('open_at', '개찰 예정')]:
        value = summary.get(key)
        elapsed = bool(value and value <= now)
        summary['timeline'].append(dict(key=key, label=label, at=value,
            elapsed=elapsed and (not cancelled or key == 'posted_at'),
            hint='취소된 공고 일정' if cancelled and key != 'posted_at' else
                 ('시각 경과 · 결과 미확인' if key == 'open_at' and elapsed else
                  ('시각 경과' if elapsed else ('예정' if value else '미제공')))))
    opening = summary.get('open_at')
    summary['opening_schedule'] = '취소 공고' if cancelled else (
        '개찰 예정시각 경과' if opening and opening <= now else ('개찰 예정' if opening else '개찰일 미제공'))
    # No result collector exists yet. Elapsed time/provider progress is not an award.
    summary['result_message'] = '개찰 결과 자동 연동 전입니다. 공식 원문에서 결과를 확인하세요.'
    return summary


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
    url = safe_url(summary.get('detail_url'), source)
    summary['original_is_search'] = not bool(url)
    summary['original_url'] = url or ('https://srm.kepco.net/' if source == 'kepco' else 'https://www.g2b.go.kr/')
    summary['attachments'] = attachment_links(raw, summary, source)
    summary['collected_fields'] = list(fields(raw))
    return presentation(summary, raw)
