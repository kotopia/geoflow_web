"""Central-only aggregate reporting; never contacts G2B or tenant databases."""
from datetime import timedelta

from django.conf import settings
from django.db.models import Count
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from .models import ApiBudget, CollectionJob, CollectionRule, Notice
from .policy import minute, retention_start
from .service import central_alias


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
        rows.append(dict(rule=rule, job=job, progress=progress, stale=stale,
                         window_start=parse_datetime(progress.get("start", "")),
                         window_end=parse_datetime(progress.get("end", "")),
                         state=statuses.get(job.status, "확인 필요") if job else "작업 미등록",
                         backfill_complete=bool(job and job.backfill_cursor >= job.backfill_end)))
    successful = [job.last_success_at for job in jobs.values() if job.last_success_at]
    budget = ApiBudget.objects.using(alias).filter(day=minute(now).date()).first()
    notices = Notice.objects.using(alias)
    return dict(rows=rows, total=notices.count(), expired=notices.filter(posted_at__lt=retention_start(now)).count(),
                active=sum(rule.active for rule in rules), running=sum(job.status == "running" for job in jobs.values()),
                requested=sum(job.requested for job in jobs.values()),
                last_success=max(successful) if successful else None,
                api_used=budget.used if budget else 0,
                api_budget=getattr(settings, "G2B_CENTRAL_DAILY_BUDGET", 500))
