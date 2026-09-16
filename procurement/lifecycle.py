"""Durable coverage and local source reuse; no provider requests."""
import uuid
from datetime import timedelta
from django.db import transaction
from django.utils import timezone
from .models import CollectionJob, CollectionWindow, Notice
from .policy import minute, retention_start


def coverage_gap(job, now):
    from .service import central_alias
    cursor = max(job.backfill_start or retention_start(job.backfill_end), retention_start(now))
    for start, end in CollectionWindow.objects.using(central_alias()).filter(
            job=job, generation=job.generation, mode="backfill", verified=True).order_by("start").values_list("start", "end"):
        if end <= cursor:
            continue
        if start > cursor:
            return cursor, min(start, job.backfill_end)
        cursor = max(cursor, end)
    return (cursor, job.backfill_end) if cursor < job.backfill_end else None


def recent_backfill_window(job, now):
    """Newest uncovered day; receipts, not the legacy forward cursor, prove coverage."""
    from .service import central_alias
    from .period import bounds
    lower, cursor = bounds(job, now)
    if cursor <= lower:
        return None
    windows = CollectionWindow.objects.using(central_alias()).filter(
        job=job, generation=job.generation, mode="backfill", verified=True
    ).order_by("-end").values_list("start", "end")
    for start, end in windows:
        if start >= cursor:
            continue
        if end < cursor:
            return max(lower, end, cursor - timedelta(days=1)), cursor
        cursor = min(cursor, start)
        if cursor <= lower:
            return None
    return (max(lower, cursor - timedelta(days=1)), cursor) if cursor > lower else None


def match_existing(job, now, batch_size=500):
    from .service import central_alias, rule_matches
    if job.local_match_complete:
        return True
    alias = central_alias()
    qs = Notice.objects.using(alias).filter(posted_at__gte=retention_start(now), posted_at__lte=now).order_by("id")
    if job.local_match_cursor:
        qs = qs.filter(id__gt=job.local_match_cursor)
    notices = list(qs[:batch_size])
    with transaction.atomic(using=alias):
        current = CollectionJob.objects.using(alias).select_for_update().get(pk=job.pk)
        if current.generation != job.generation:
            return False
        matched = 0
        for notice in notices:
            if rule_matches(job.rule, notice.raw.get("notice", {"bidNtceNm": notice.title}),
                            {"industries": notice.raw.get("industries", [])}):
                notice.rules.add(job.rule)
                matched += 1
        job.local_matched += matched
        if notices:
            job.local_match_cursor = notices[-1].pk
        job.local_match_complete = len(notices) < batch_size
        CollectionJob.objects.using(alias).filter(pk=job.pk, generation=job.generation).update(
            local_matched=job.local_matched, local_match_cursor=job.local_match_cursor,
            local_match_complete=job.local_match_complete)
    return job.local_match_complete


def reactivate(rule, now=None):
    from .service import central_alias, enqueue_rule
    now = minute(now or timezone.now())
    with transaction.atomic(using=central_alias()):
        job = enqueue_rule(rule, now)
        CollectionJob.objects.using(central_alias()).filter(pk=job.pk).update(
            generation=uuid.uuid4(), backfill_start=retention_start(now), backfill_cursor=retention_start(now),
            backfill_end=now, backfill_status="BACKFILL_PENDING", backfill_progress={}, incremental_progress={},
            progress={}, local_match_complete=False, local_match_cursor=None, local_matched=0,
            requested=True, status="pending", error_code="")
