"""Tenant company search preferences, not company record-access permissions."""
import json
import re
from uuid import UUID

from django.db import connections
from django.http import Http404

from procurement.service import central_alias
from .repository import list_settings

KINDS = ('region', 'agency', 'include', 'exclude')


def companies(alias):
    if not alias or alias == central_alias():
        raise ValueError('테넌트 회사 정보를 확인하세요.')
    # Reuse the tenant's org-unit identity. Do not infer company/branch from names.
    with connections[alias].cursor() as cur:
        cur.execute('SELECT id,name,address FROM ops.my_org_units ORDER BY name,id')
        return [dict(id=str(pk), name=name, address=address or '') for pk, name, address in cur.fetchall()]


def context(alias, value):
    items = companies(alias)
    selected = None
    if value:
        try:
            key = str(UUID(str(value)))
        except (ValueError, TypeError, AttributeError):
            raise Http404('회사를 확인하세요.')
        selected = next((item for item in items if item['id'] == key), None)
        if selected is None:
            raise Http404('이 테넌트의 회사가 아닙니다.')
    return items, selected


def load(alias, company_id):
    with connections[alias].cursor() as cur:
        cur.execute('SELECT settings FROM bid.company_search_profiles WHERE company_id=%s', [company_id])
        row = cur.fetchone()
    return (json.loads(row[0]) if isinstance(row[0], str) else row[0]) if row else None


def defaults(alias):
    from procurement.preferences import selected_conditions
    catalog = list_settings(alias)
    return dict(condition_ids=selected_conditions(alias),
                selections={kind: [r['id'] for r in catalog.get(kind, []) if r['active']] for kind in KINDS},
                sources=[], local_region_id='')


def effective(alias, company_id):
    value = load(alias, company_id)
    return (value, False) if value is not None else (defaults(alias), True)


def filters(alias, settings):
    catalog = list_settings(alias)
    return {kind: [row for row in catalog.get(kind, [])
                   if row['id'] in settings.get('selections', {}).get(kind, [])] for kind in KINDS}


def is_local_region(row):
    # A province/metropolitan-city-wide restriction is not a municipal 관내 badge.
    name = row.get('name', '').strip()
    return bool(re.search(r'(?:^|\s)[가-힣]+(?:시|군|구)$', name)) and not name.endswith(('광역시', '특별시', '특별자치시'))


def validate(alias, data, previous):
    from procurement.preferences import choices
    available = {str(r.pk): r for r in choices(alias)}
    selected = set(data.get('condition_ids', []))
    if not selected <= available.keys():
        raise ValueError('등록된 업종·수집 키워드를 선택하세요.')
    if any(not available[key].active for key in selected - set(previous.get('condition_ids', []))):
        raise ValueError('중앙에서 중지한 조건은 새로 선택할 수 없습니다.')
    catalog = list_settings(alias)
    selections = {}
    for kind in KINDS:
        ids = set(data.get('selections', {}).get(kind, []))
        if not ids <= {r['id'] for r in catalog.get(kind, [])}:
            raise ValueError('이 테넌트에 등록된 검색 항목을 선택하세요.')
        selections[kind] = sorted(ids)
    sources = set(data.get('sources', []))
    if not sources <= {'g2b', 'kepco'}:
        raise ValueError('지원하는 공고 출처를 선택하세요.')
    local = data.get('local_region_id', '')
    if local and local not in {r['id'] for r in catalog.get('region', []) if is_local_region(r)}:
        raise ValueError('관내 기준은 시·군·구 지역으로 선택하세요.')
    return dict(condition_ids=sorted(selected), selections=selections, sources=sorted(sources), local_region_id=local)


def save(alias, company_id, data):
    _, company = context(alias, company_id)
    if company is None:
        raise ValueError('설정할 회사를 선택하세요.')
    previous, _ = effective(alias, company_id)
    value = validate(alias, data, previous)
    with connections[alias].cursor() as cur:
        cur.execute('''INSERT INTO bid.company_search_profiles(company_id,settings) VALUES (%s,%s::jsonb)
            ON CONFLICT(company_id) DO UPDATE SET settings=excluded.settings,updated_at=now()''',
                    [company_id, json.dumps(value)])


def local_badge(notice, settings, catalog):
    local = next((r for r in catalog.get('region', []) if r['id'] == settings.get('local_region_id')), None)
    if not local or not is_local_region(local):
        return False
    # Exact restriction only. Never use agency address, project title or substring.
    terms = {re.sub(r'\s+', '', str(v)) for v in [local['name'], *local.get('aliases', [])]
             if v and is_local_region({'name': str(v)})}
    return re.sub(r'\s+', '', notice.get('region_text') or '') in terms


def badges(notice):
    result = []
    for field in ('contract_method_name', 'bid_method_name', 'award_method_name'):
        value = str(notice.get(field) or '').strip()
        for term, label in [('협상', '협상'), ('수의시담', '수의시담'), ('전자시담', '전자시담'),
                            ('직찰', '직찰'), ('직접입찰', '직접입찰')]:
            if term in value and label not in result:
                result.append(label)
    return result
