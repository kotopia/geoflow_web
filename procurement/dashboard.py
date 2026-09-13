"""Central-only aggregate reporting; never contacts G2B or tenant databases."""
from datetime import timedelta

from django.conf import settings
from django.db.models import Count
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from .models import ApiBudget, CollectionJob, CollectionRule, Notice, CollectionWindow
from .policy import minute, retention_start
from .service import central_alias


def lane_stats(progress):
    queries = list(progress.get("api_page_cache", {}).values()) or progress.get("api_queries", [])
    query = next((q for q in queries if q["operation"] == "getBidPblancListInfoServcPPSSrch"), {})
    pages = query.get("pages", [])
    total = query.get("totalCount")
    size = query.get("numOfRows", 999)
    return dict(current_page=len(pages) if query.get("complete") else len(pages)+1,
                last_success_page=len(pages), total_count=total, total_pages=(total+size-1)//size if total else 0,
                received=sum(p.get("received", 0) for p in pages),
                start=parse_datetime(progress.get("start", "")), end=parse_datetime(progress.get("end", "")))


def snapshot():
    now = timezone.now()
    alias = central_alias()
    rules = list(CollectionRule.objects.using(alias).annotate(stored_count=Count("notices")).order_by("created_at"))
    jobs = {job.rule_id: job for job in CollectionJob.objects.using(alias).all()}
    statuses = {"pending": "대기", "running": "수집 중", "success": "최근 구간 완료", "failed": "실패"}
    rows = []
    for rule in rules:
        job = jobs.get(rule.pk)
        progress = job.progress if job else {}
        updated = parse_datetime(progress.get("updated_at", ""))
        stale = bool(job and job.status == "running" and updated and
                     timezone.is_aware(updated) and now - updated > timedelta(minutes=10))
        totals = {key: 0 for key in ("source_total", "received", "duplicates", "inserted", "updated", "unchanged", "matched", "rejected", "expired")}
        if job:
            for metrics in CollectionWindow.objects.using(alias).filter(job=job, generation=job.generation,
                    mode="backfill", verified=True).values_list("metrics", flat=True):
                for key in totals:
                    totals[key] += metrics.get(key) or 0
        lifecycle = job.backfill_status if job else "NEW"
        if not rule.active:
            lifecycle = "PAUSED"
        elif job and job.backfill_status == "BACKFILL_COMPLETE" and job.last_incremental_success:
            lifecycle = "INCREMENTAL"
        rows.append(dict(rule=rule, job=job, progress=progress, stale=stale,
                         lifecycle=lifecycle, totals=totals,
                         backfill_start=job.backfill_start or retention_start(job.backfill_end) if job else None,
                         backfill_page=lane_stats(job.backfill_progress) if job else {},
                         window_start=parse_datetime(progress.get("start", "")),
                         window_end=parse_datetime(progress.get("end", "")),
                         state=statuses.get(job.status, "확인 필요") if job else "작업 미등록",
                         backfill_complete=bool(job and job.backfill_status == "BACKFILL_COMPLETE")))
    successful = [job.last_success_at for job in jobs.values() if job.last_success_at]
    budget = ApiBudget.objects.using(alias).filter(day=minute(now).date()).first()
    notices = Notice.objects.using(alias)
    return dict(rows=rows, total=notices.count(), expired=notices.filter(posted_at__lt=retention_start(now)).count(),
                active=sum(rule.active for rule in rules), running=sum(job.status == "running" for job in jobs.values()),
                requested=sum(job.requested for job in jobs.values()),
                last_success=max(successful) if successful else None,
                api_used=budget.used if budget else 0,
                api_received=budget.received if budget else 0, inserted=budget.inserted if budget else 0,
                updated=budget.updated if budget else 0,
                api_budget=getattr(settings, "G2B_CENTRAL_DAILY_BUDGET", 500))
