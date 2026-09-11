"""Cross-database reads: tenant predicates BEFORE central count/pagination."""
from datetime import datetime

from django.db import connections
from django.db.models import Q
from django.utils import timezone

from geoflow_ops.bids.repository import load_filters, REVIEW_STATUSES
from .models import Notice, CollectionJob
from .policy import retention_start
from .service import central_alias, enabled


def review_rows(alias):
    enabled(alias)  # fail closed for missing or central context
    with connections[alias].cursor() as cur:
        cur.execute("SELECT central_notice_id,status,memo FROM bid.central_reviews")
        return {str(row[0]): {"review_status": row[1], "memo": row[2]} for row in cur.fetchall()}


def query_notices(alias, query="", review_status="", include_all=False):
    reviews = review_rows(alias)
    qs = Notice.objects.using(central_alias()).filter(posted_at__gte=retention_start(timezone.now()))
    if review_status in REVIEW_STATUSES:
        if review_status == "unreviewed":
            qs = qs.exclude(pk__in=[pk for pk, r in reviews.items() if r["review_status"] != "unreviewed"])
        else:
            qs = qs.filter(pk__in=[pk for pk, r in reviews.items() if r["review_status"] == review_status])
    else:
        qs = qs.exclude(pk__in=[pk for pk, r in reviews.items() if r["review_status"] == "excluded"])
    if query:
        qs = qs.filter(Q(title__icontains=query[:100]) | Q(number__icontains=query[:100]) |
                       Q(agency__icontains=query[:100]) | Q(demand_agency__icontains=query[:100]))
    if not include_all:
        filters = load_filters(alias)
        if not any(filters.get(k) for k in ("region", "industry", "agency", "include")):
            return qs.none(), reviews
        for kind, field in (("region", "region_text"), ("industry", "industry_text"), ("agency", "agency")):
            if not filters.get(kind):
                continue
            condition = Q()
            for item in filters[kind]:
                for term in [item["name"], *item.get("aliases", [])]:
                    if term:
                        condition |= Q(**{field + "__icontains": term})
            if kind in ("region", "industry"):
                # Discovery candidates, never a positive participation eligibility claim.
                condition |= Q(**{kind + "_known": False})
                condition |= Q(**{field + "__icontains": "제한 없음"})
            qs = qs.filter(condition)
        for rule_type in ("include", "exclude"):
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
    qs = qs.order_by("-posted_at", "id")[max(0, offset):max(0, offset) + (30 if limit == 30 else 15)]
    result = []
    for notice in qs.defer("raw"):
        row = dict(notice.summary, id=str(notice.pk), title=notice.title, posted_at=notice.posted_at,
                   bid_close_at=notice.close_at, needs_review=True, reasons=[],
                   review_status="unreviewed", memo="")
        row.update(reviews.get(str(notice.pk), {}))
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
    if status not in REVIEW_STATUSES:
        raise ValueError("검토 상태를 확인하세요.")
    notice = Notice.objects.using(central_alias()).filter(pk=notice_id).first()
    if notice is None:
        raise ValueError("공고를 찾을 수 없습니다. 보관기간 만료 여부를 확인하세요.")
    with connections[alias].cursor() as cur:
        cur.execute("""INSERT INTO bid.central_reviews
          (central_notice_id,notice_number,notice_order,title,detail_url,status,memo,updated_by)
          VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
          ON CONFLICT(central_notice_id) DO UPDATE SET status=excluded.status,memo=excluded.memo,
          updated_by=excluded.updated_by,updated_at=now()""",
          [str(notice.pk), notice.number, notice.order, notice.title, notice.summary.get("detail_url"),
           status, memo[:2000], updated_by[:255]])
