"""Cross-database reads: tenant predicates BEFORE central count/pagination."""
from datetime import datetime

from django.db import connections
from django.db.models import F, Q
from django.utils import timezone

from geoflow_ops.bids.repository import load_filters, REVIEW_STATUSES
from .models import Notice, CollectionJob
from .preferences import selected_ids
from .policy import retention_start
from .service import central_alias, enabled


def review_rows(alias):
    enabled(alias)  # fail closed for missing or central context
    with connections[alias].cursor() as cur:
        cur.execute("SELECT central_notice_id,status,memo FROM bid.central_reviews")
        return {str(row[0]): {"review_status": row[1], "memo": row[2]} for row in cur.fetchall()}


def nationwide_q():
    # Only an explicit unrestricted value counts as nationwide; absent data does not.
    return Q(region_known=True, region_text__regex=r"^\s*(전국(\s*\(지역\s*제한\s*없음\))?|지역\s*제한\s*없음|제한\s*없음)\s*$")


def region_q(items):
    condition = Q(pk__in=[])
    for item in items:
        for term in [item["name"], *item.get("aliases", [])]:
            if term:
                condition |= Q(region_text__icontains=term)
    return condition


def query_notices(alias, query="", review_status="", include_all=False, region="all", personal_state=None, personal_view="all", include_closed=True, date_from=None, date_to=None, sort="new", apply_extra=False, include_excluded=False, sources=None, search_profile=None):
    reviews = review_rows(alias)
    qs = Notice.objects.using(central_alias()).filter(posted_at__gte=retention_start(timezone.now()))
    state = personal_state or {}
    hidden = [pk for pk, value in state.items() if value['hidden']]
    saved = [pk for pk, value in state.items() if value['saved']]
    if personal_view == 'hidden':
        qs = qs.filter(pk__in=hidden)
    else:
        qs = qs.exclude(pk__in=hidden)
        if personal_view == 'saved':
            qs = qs.filter(pk__in=saved)
    if not include_closed and personal_view == 'all':
        qs = qs.filter(Q(close_at__isnull=True) | Q(close_at__gt=timezone.now())).filter(Q(summary__notice_status__isnull=True) | ~Q(summary__notice_status__in=['cancelled', 'closed']))
    if date_from:
        qs = qs.filter(posted_at__date__gte=date_from)
    if date_to:
        qs = qs.filter(posted_at__date__lte=date_to)
    if review_status in REVIEW_STATUSES:
        if review_status == "unreviewed":
            qs = qs.exclude(pk__in=[pk for pk, r in reviews.items() if r["review_status"] != "unreviewed"])
        else:
            qs = qs.filter(pk__in=[pk for pk, r in reviews.items() if r["review_status"] == review_status])
    elif personal_view == "all" and not include_excluded:
        qs = qs.exclude(pk__in=[pk for pk, r in reviews.items() if r["review_status"] == "excluded"])
    if sources is not None:
        qs = qs.filter(source__in=sources)
    if query:
        qs = qs.filter(Q(title__icontains=query[:100]) | Q(number__icontains=query[:100]) |
                       Q(agency__icontains=query[:100]) | Q(demand_agency__icontains=query[:100]))
    if personal_view in {'saved', 'hidden'}:
        return qs, reviews
    if search_profile is not None:
        from geoflow_ops.bids.profiles import filters as profile_filters
        filters = profile_filters(alias, search_profile)
    else:
        filters = load_filters(alias)
    # The central rule relation is authoritative. Multiple selected rules are OR;
    # distinct prevents double counting a notice belonging to several rules.
    if not include_all:
        if search_profile is not None:
            from .conditions import resolve_rule_ids
            rule_ids = resolve_rule_ids(search_profile.get("condition_ids", []))
        else:
            rule_ids = selected_ids(alias, filters)
        qs = qs.filter(rules__id__in=rule_ids).distinct()
        if search_profile and search_profile.get("sources") and sources is None:
            qs = qs.filter(source__in=search_profile["sources"])
    regions = filters.get("region", [])
    unknown = Q(region_known=False) | Q(region_text="")
    if region == "nationwide":
        qs = qs.filter(nationwide_q())
    elif region == "unknown":
        qs = qs.filter(unknown)
    elif region not in {"all", "configured"}:
        chosen = [item for item in regions if item["id"] == region]
        qs = qs.filter(region_q(chosen)).exclude(nationwide_q()).exclude(unknown)
    elif regions and not include_all:
        qs = qs.filter(region_q(regions) | nationwide_q() | unknown)
    if apply_extra and filters.get("agency"):
        condition = Q(pk__in=[])
        for item in filters["agency"]:
            for term in [item["name"], *item.get("aliases", [])]:
                if term:
                    condition |= Q(agency__icontains=term) | Q(demand_agency__icontains=term)
        qs = qs.filter(condition)
    for rule_type in (("include", "exclude") if apply_extra else ()):
        condition = Q()
        for rule in filters.get(rule_type, []):
            import re
            term = rule["keyword"].strip()
            if term:
                pattern = re.escape(term)
                if term.isascii() and term.isalnum():
                    pattern = r"(?<![0-9a-z])" + pattern + r"(?![0-9a-z])"
                condition |= Q(title__iregex=pattern)
        if condition:
            qs = qs.exclude(condition) if rule_type == "exclude" else qs.filter(condition)
    return qs, reviews


def count_notices(alias, **kwargs):
    return query_notices(alias, **kwargs)[0].count()


def list_notices(alias, limit=15, offset=0, **kwargs):
    qs, reviews = query_notices(alias, **kwargs)
    qs = qs.order_by(*(["close_at", "-posted_at", "id"] if kwargs.get("sort") == "deadline" else ["-posted_at", "id"]))[max(0, offset):max(0, offset) + (30 if limit == 30 else 15)]
    result = []
    # Fetch only the two display fields, not potentially large source payloads.
    qs = qs.annotate(display_award=F("raw__notice__sucsfbidMthdNm"),
                     display_registration=F("raw__notice__bidQlfctRgstDt")).defer("raw")
    for notice in qs:
        row = dict(notice.summary, id=str(notice.pk), title=notice.title, posted_at=notice.posted_at,
                   bid_close_at=notice.close_at, needs_review=True, reasons=[],
                   review_status="unreviewed", memo="")
        row.update(reviews.get(str(notice.pk), {}))
        row["award_method_name"] = notice.display_award or ""
        from geoflow_ops.bids.sync import _date
        try:
            row["registration_close_at"] = _date(notice.display_registration)
        except (ValueError, TypeError):
            row["registration_close_at"] = None
        if notice.close_at and notice.close_at <= timezone.now() and row.get("notice_status") != "cancelled":
            row["notice_status"] = "closed"
        result.append(row)
    return result


def latest_sync(alias):
    enabled(alias)
    job = CollectionJob.objects.using(central_alias()).filter(rule__active=True).order_by("-last_success_at").first()
    if not job:
        return None
    failed = CollectionJob.objects.using(central_alias()).filter(rule__active=True, status="failed").exists()
    return dict(started_at=job.last_success_at, status="일부 수집 실패" if failed else job.status,
                fetched_count=job.fetched_count, inserted_count="—", updated_count="—", error_message="")


def save_review(alias, notice_id, *, status, memo, updated_by):
    enabled(alias)
    if status is not None and status not in REVIEW_STATUSES:
        raise ValueError("검토 상태를 확인하세요.")
    notice = Notice.objects.using(central_alias()).filter(pk=notice_id).first()
    if notice is None:
        raise ValueError("공고를 찾을 수 없습니다. 보관기간 만료 여부를 확인하세요.")
    with connections[alias].cursor() as cur:
        cur.execute("""INSERT INTO bid.central_reviews
          (central_notice_id,notice_number,notice_order,title,detail_url,status,memo,updated_by)
          VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
          ON CONFLICT(central_notice_id) DO UPDATE SET status=CASE WHEN %s THEN bid.central_reviews.status ELSE excluded.status END,memo=excluded.memo,
          updated_by=excluded.updated_by,updated_at=now()""",
          [str(notice.pk), notice.number, notice.order, notice.title, notice.summary.get("detail_url"),
           status or "unreviewed", memo[:2000], updated_by[:255], status is None])
