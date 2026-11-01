"""Canonical company dashboard rules, always explicitly tenant scoped."""
from datetime import date
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import connections
from django.utils import timezone
from geoflow_ops.company_models import CompanyProfile, CompanyRevenue, CompanyHeadcount, CompanyCredit, CompanyRegistration, CompanyEvidence
from geoflow_ops.models import ProcessEvent, Attachment

FORMS_KINDS = ('registration', 'revenue', 'headcount', 'credit', 'event')
EVIDENCE_PURPOSE = {'registration':'business_registration', 'headcount':'business_registration', 'credit':'company_financial', 'revenue':'company_financial'}


def enabled(alias=None):
    from control.middleware import current_db_alias
    alias = alias or current_db_alias()
    return bool(getattr(settings, 'GEOFLOW_COMPANY_OVERVIEW_ENABLED', False) and alias in getattr(settings, 'GEOFLOW_COMPANY_OVERVIEW_TENANTS', ()))


def current_headcount(alias, company_id):
    # Reuse HR's configured retired-status interpretation. Never return staff PII.
    from geoflow_ops.views_employee_profile import _retired_status_codes
    retired = list(set(_retired_status_codes(alias)) | {'퇴사', '퇴직'})
    today = timezone.localdate()
    with connections[alias].cursor() as cur:
        cur.execute('''SELECT COUNT(*) FROM hr.employee_profile
          WHERE org_unit_id=%s AND is_deleted=false
            AND (hire_date IS NULL OR hire_date<=%s)
            AND (term_date IS NULL OR term_date>%s)
            AND NOT (COALESCE(status,'') = ANY(%s))''', [str(company_id), today, today, retired])
        return cur.fetchone()[0]


def annual_series(alias, company_id, years, *, finance):
    last_year = timezone.localdate().year - 1
    labels = list(range(last_year - years + 1, last_year + 1))
    heads = dict(CompanyHeadcount.objects.using(alias).filter(company_id=company_id, year__in=labels).values_list('year', 'count'))
    revenue = {}
    if finance:
        revenue = {r.year: {'amount':str(r.amount), 'confirmed':r.confirmed, 'source':r.source} for r in CompanyRevenue.objects.using(alias).filter(company_id=company_id, year__in=labels)}
    return [{'year':year, 'headcount':heads.get(year), 'revenue':revenue.get(year)} for year in labels]


def validate_parent(alias, company_id, parent_id, node_kind):
    from geoflow_ops.models import MyOrgUnit
    if node_kind == 'branch' and not parent_id:
        raise ValidationError('지점은 소속 기업을 선택하세요.')
    if node_kind == 'branch' and CompanyProfile.objects.using(alias).filter(parent_id=company_id).exists():
        raise ValidationError('하위 기업이 있는 기업은 지점으로 변경할 수 없습니다.')
    visited = {company_id}
    current = parent_id
    while current:
        if current in visited:
            raise ValidationError('상위 기업 관계가 순환할 수 없습니다.')
        visited.add(current)
        if not MyOrgUnit.objects.using(alias).filter(pk=current).exists():
            raise ValidationError('현재 테넌트의 기업을 선택하세요.')
        profile = CompanyProfile.objects.using(alias).filter(company_id=current).first()
        if profile and profile.node_kind == 'branch':
            raise ValidationError('지점을 상위 기업으로 지정할 수 없습니다.')
        current = profile.parent_id if profile else None


def sync_source_event(alias, record, kind, actor):
    """Called under the company row lock/transaction; same source, same event."""
    if kind not in {'registration','credit'}:
        return
    title = f'{record.name} · {record.get_status_display()}' if kind == 'registration' else f'{record.agency} 신용평가 · {record.grade}'
    occurred = (record.issued_on or record.occurred_on) if kind == 'registration' else record.evaluated_on
    event = ProcessEvent.objects.using(alias).filter(pk=record.event_id).first() if record.event_id else None
    if event is None:
        event = ProcessEvent(scope_type='orgunit', scope_id=record.company_id, stage='company', event_type='company_'+kind, created_by=actor)
    event.title = title
    event.occurred_at = occurred
    event.status = 'done'
    event.payload = {'company_source_kind':kind, 'company_source_id':str(record.pk)}
    event.save(using=alias)
    if record.event_id != event.pk:
        record.event_id = event.pk
        record.save(using=alias, update_fields=['event'])


def evidence_candidates(alias, company_id, kind):
    return Attachment.objects.using(alias).filter(entity_type='orgunit', entity_id=company_id, purpose=EVIDENCE_PURPOSE[kind], active=True, is_deleted=False, deleted_at__isnull=True).order_by('-created_at')


def validate_evidence(alias, company_id, kind, ids):
    from uuid import UUID
    try:
        ids = {UUID(str(value)) for value in ids}
    except (TypeError, ValueError):
        raise ValidationError('첨부파일 식별자가 올바르지 않습니다.')
    if len(ids) > 50:
        raise ValidationError('증빙은 최대 50개까지 연결할 수 있습니다.')
    found = set(evidence_candidates(alias, company_id, kind).filter(pk__in=ids).values_list('pk', flat=True))
    if ids != found:
        raise ValidationError('다른 기업의 파일, 삭제된 파일 또는 허용되지 않는 증빙입니다.')
    return found


def replace_evidence(alias, record, kind, ids):
    qs = CompanyEvidence.objects.using(alias).filter(company_id=record.company_id, record_kind=kind, record_id=record.pk)
    qs.exclude(attachment_id__in=ids).delete()
    for attachment_id in ids:
        CompanyEvidence.objects.using(alias).get_or_create(company_id=record.company_id, record_kind=kind, record_id=record.pk, attachment_id=attachment_id)


def record_evidence(alias, company_id, kind, record_id):
    return CompanyEvidence.objects.using(alias).filter(company_id=company_id, record_kind=kind, record_id=record_id, attachment__active=True, attachment__is_deleted=False, attachment__deleted_at__isnull=True).select_related('attachment')


def company_documents(alias, company_id, *, finance, today=None):
    """Unified presentation over canonical typed records, without copying their ownership."""
    from collections import defaultdict
    today = today or timezone.localdate()
    registrations = list(CompanyRegistration.objects.using(alias).filter(company_id=company_id).order_by('-occurred_on','-id'))
    credits = list(CompanyCredit.objects.using(alias).filter(company_id=company_id).order_by('-evaluated_on','-id')) if finance else []
    evidence = defaultdict(list)
    kinds = ['registration','credit'] if finance else ['registration']
    links = CompanyEvidence.objects.using(alias).filter(company_id=company_id,record_kind__in=kinds,
        attachment__active=True,attachment__is_deleted=False,attachment__deleted_at__isnull=True).select_related('attachment')
    for link in links:
        evidence[(link.record_kind,link.record_id)].append(link)
    rows = []
    for kind, records in [('registration',registrations),('credit',credits)]:
        replaced = {r.previous_id for r in records if r.previous_id}
        for record in records:
            expired = bool(record.expires_on and record.expires_on < today)
            cancelled = kind == 'registration' and record.status == 'cancelled'
            pending = kind == 'registration' and record.status == 'pending'
            previous = record.pk in replaced
            due = bool(record.expires_on and 0 <= (record.expires_on-today).days <= 30 and not previous and not cancelled and not pending)
            status = '이전 이력' if previous else '취소' if cancelled else '진행중' if pending else '만료' if expired else '만료 임박' if due else '유효'
            rows.append({'record':record,'id':record.pk,'kind':kind,
                'name':record.name if kind=='registration' else record.rating_type + ' · ' + record.grade,
                'category':record.get_kind_display() if kind=='registration' else '신용평가',
                'group':'credit' if kind=='credit' else 'certification' if record.kind=='certification' else 'registration',
                'issuer':record.issuer if kind=='registration' else record.agency,
                'date':(record.issued_on or record.occurred_on) if kind=='registration' else record.evaluated_on,
                'expires_on':record.expires_on,'status':status,'previous':previous,'due':due,
                'active':not(previous or cancelled or pending or expired),
                'tone':'secondary' if previous or expired or cancelled else 'warning' if due or pending else 'success',
                'evidence':evidence[(kind,record.pk)]})
    return sorted(rows,key=lambda r:(r['date'],str(r['id'])),reverse=True)


def document_history(rows, selected):
    """Only explicit predecessor links belong to a renewal chain; names are not identifiers."""
    by_id = {r['id']:r for r in rows if r['kind']==selected['kind']}
    included = {selected['id']}
    changed = True
    while changed:
        changed = False
        for key,row in by_id.items():
            previous = row['record'].previous_id
            if key in included or previous in included:
                for value in (key,previous):
                    if value in by_id and value not in included:
                        included.add(value); changed = True
    return [row for row in rows if row['kind']==selected['kind'] and row['id'] in included]
