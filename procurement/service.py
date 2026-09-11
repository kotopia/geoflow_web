import json
import re
from contextlib import contextmanager
from datetime import timedelta

from django.conf import settings
from django.core.serializers.json import DjangoJSONEncoder
from django.db import connections, transaction
from django.utils import timezone

from geoflow_ops.bids.client import G2BError
from geoflow_ops.bids.sync import _normalized_notice
from geoflow_ops.bids.matcher import keyword_matches
from .client import Client
from .models import CollectionJob, CollectionRule, Notice, NoticeRevision
from .policy import retention_start, minute, next_window, canonical_order, notice_id


def central_alias():
    return getattr(settings, "CENTRAL_DB_ALIAS", "default")


def enabled(alias):
    if not alias or alias == central_alias():
        raise ValueError("명시적인 회사 데이터베이스가 필요합니다.")
    return alias in getattr(settings, "G2B_CENTRAL_TENANT_ALIASES", ())


def enqueue_rule(rule, now=None):
    now = minute(now or timezone.now())
    job, created = CollectionJob.objects.using(central_alias()).get_or_create(
        rule=rule, defaults=dict(backfill_cursor=retention_start(now), backfill_end=now,
                                 live_cursor=now, due_at=now),
    )
    if not created:
        CollectionJob.objects.using(central_alias()).filter(pk=job.pk).update(requested=True)
    return job


def request_sync():
    # Only active central rules; a tenant cannot expand the shared collection scope.
    return CollectionJob.objects.using(central_alias()).filter(rule__active=True).update(requested=True)


@contextmanager
def worker_lock():
    conn = connections[central_alias()]
    if conn.vendor != "postgresql":
        raise RuntimeError("중앙 수집기는 PostgreSQL에서만 실행합니다.")
    with conn.cursor() as cur:
        cur.execute("SELECT pg_try_advisory_lock(714302611)")
        acquired = cur.fetchone()[0]
    try:
        yield acquired
    finally:
        if acquired:
            with conn.cursor() as cur:
                cur.execute("SELECT pg_advisory_unlock(714302611)")


def rule_matches(rule, row, details):
    if rule.kind == "keyword":
        return keyword_matches(rule.value, row.get("bidNtceNm"))
    # Preserve token boundaries: code 1468 must not match 11468.
    text = json.dumps(details["industries"], ensure_ascii=False)
    return re.search(r"(?<!\d)" + re.escape(rule.value) + r"(?!\d)", text) is not None


def store_notice(row, details, rule, now):
    normalized = _normalized_notice(row, details["regions"], details["industries"], [])
    posted = normalized["posted_at"]
    if not posted:
        raise G2BError("MISSING_POSTED_DATE", "공고게시일을 확인할 수 없습니다.")
    if posted < retention_start(now):
        return
    # Never infer 'no restrictions' from an empty successful auxiliary response.
    summary = json.loads(json.dumps(normalized, cls=DjangoJSONEncoder))
    raw = dict(normalized["raw_payload"], products=details["products"])
    import hashlib
    digest = hashlib.sha256(json.dumps(raw, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    summary.pop("raw_payload", None)
    summary["industry_parse_status"] = "review_required" if details["industries"] else "unknown"
    summary["direct_production_parse_status"] = "unknown"
    alias = central_alias()
    with transaction.atomic(using=alias):
        notice, _ = Notice.objects.using(alias).update_or_create(
            id=notice_id(normalized["bid_notice_no"], normalized["bid_notice_ord"]),
            defaults=dict(number=normalized["bid_notice_no"], order=canonical_order(normalized["bid_notice_ord"]),
                          title=normalized["title"], posted_at=posted, close_at=normalized["bid_close_at"],
                          agency=normalized["notice_agency_name"], demand_agency=normalized["demand_agency_name"],
                          estimated_price=normalized["estimated_price"], region_text=normalized["region_text"],
                          industry_text=normalized["industry_text"], region_known=bool(normalized["region_text"]),
                          industry_known=bool(normalized["industry_text"]), summary=summary, raw=raw,
                          payload_hash=digest, source_updated_at=normalized["source_updated_at"], last_seen_at=now),
        )
        notice.rules.add(rule)
        NoticeRevision.objects.using(alias).get_or_create(notice=notice, payload_hash=digest, defaults={"raw": raw})


def run_step(job, client, now=None):
    """Persist per-notice; advance the cursor only after the entire window succeeds.

    Retrying a partially persisted window is safe. Errors expose codes only.
    """
    now = minute(now or timezone.now())
    alias = central_alias()
    live = job.requested or job.due_at <= now
    start, end = next_window(max(job.live_cursor, retention_start(now)), now) if live else next_window(
        max(job.backfill_cursor, retention_start(now)), job.backfill_end)
    if not live and start >= end:
        return False
    if live:
        start -= timedelta(hours=2)
    CollectionJob.objects.using(alias).filter(pk=job.pk).update(status="running", requested=False)
    try:
        rows = client.search(job.rule, start, end)
        selected = {(r.get("bidNtceNo"), canonical_order(r.get("bidNtceOrd"))): r for r in rows}
        # Old notices can change outside the posting-date search window.
        changes = client.changes(start, end) if live else []
        for row in changes:
            selected[(row.get("bidNtceNo"), canonical_order(row.get("bidNtceOrd")))] = row
        search_keys = {(r.get("bidNtceNo"), canonical_order(r.get("bidNtceOrd"))) for r in rows}
        for key, row in selected.items():
            if not key[0]:
                raise G2BError("MISSING_NOTICE_KEY", "공고 식별자가 없습니다.")
            existing = Notice.objects.using(alias).filter(number=key[0], order=key[1]).first()
            if existing and existing.raw.get("notice") == row:
                details = {name: existing.raw.get(name, []) for name in ("regions", "industries", "products")}
            else:
                details = client.details(row)
            known = Notice.objects.using(alias).filter(number=key[0], order=key[1], rules=job.rule).exists()
            selected_by_industry = job.rule.kind == "industry" and key in search_keys
            if selected_by_industry or known or rule_matches(job.rule, row, details):
                store_notice(row, details, job.rule, now)
        updates = dict(status="success", error_code="", last_success_at=now, fetched_count=len(selected))
        if live:
            updates.update(live_cursor=end, due_at=now + timedelta(hours=1))
        else:
            updates.update(backfill_cursor=end)
        CollectionJob.objects.using(alias).filter(pk=job.pk).update(**updates)
        return True
    except Exception as exc:
        code = exc.code if isinstance(exc, G2BError) else "COLLECTION_ERROR"
        CollectionJob.objects.using(alias).filter(pk=job.pk).update(status="failed", error_code=code)
        raise


def run_worker(budget=100, max_steps=10):
    with worker_lock() as acquired:
        if not acquired:
            return 0
        client = Client(budget=budget)
        jobs = CollectionJob.objects.using(central_alias()).filter(rule__active=True).select_related("rule").order_by("due_at", "id")
        completed = 0
        for _ in range(max_steps):
            progress = False
            for job in jobs.all():
                if completed >= max_steps:
                    return completed
                try:
                    changed = run_step(job, client)
                    completed += int(changed)
                    progress |= changed
                except G2BError:
                    return completed
            if not progress:
                break
        return completed
