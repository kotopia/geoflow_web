"""Read-only aggregate audit; no API calls, raw notices, or tenant data."""
import json
from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand
from django.core.serializers.json import DjangoJSONEncoder
from django.db import connections, transaction
from django.db.models import Count, Min, Max
from django.utils import timezone

from procurement.models import CollectionRule, CollectionJob, Notice, ApiBudget
from procurement.policy import minute, retention_start
from procurement.service import central_alias
from procurement.dashboard import snapshot, lane_stats
from procurement.lifecycle import recent_backfill_window


class Command(BaseCommand):
    help = "Report central collection counts, checkpoints and budgets without writes or external requests."

    def handle(self, **options):
        alias = central_alias()
        now = minute(timezone.now())
        owns_transaction = not connections[alias].in_atomic_block
        with transaction.atomic(using=alias):
            if connections[alias].vendor == "postgresql" and owns_transaction:
                with connections[alias].cursor() as cursor:
                    cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
            jobs = {j.rule_id: j for j in CollectionJob.objects.using(alias).all()}
            rules = CollectionRule.objects.using(alias).annotate(
                stored=Count("notices"), oldest=Min("notices__posted_at"), newest=Max("notices__posted_at"))
            result = dict(captured_at=now, source="central_database", display_limit=None,
                          retention_start=retention_start(now), retention_end=now, timezone="Asia/Seoul",
                          provider_key_daily_quota="unverified", historical_api_counts="not_recorded",
                          total=Notice.objects.using(alias).count(),
                          retained_total=Notice.objects.using(alias).filter(posted_at__gte=retention_start(now)).count(),
                          daily_budget=getattr(settings, "G2B_CENTRAL_DAILY_BUDGET", 500),
                          job_request_budget=getattr(settings, "G2B_JOB_REQUEST_BUDGET", 100),
                          collection_order="newest_uncovered_day_first",
                          incremental_reserve=getattr(settings, "G2B_INCREMENTAL_REQUEST_RESERVE", 100),
                          request_interval_seconds=getattr(settings, "G2B_REQUEST_INTERVAL_SECONDS", 1),
                          api_days=list(ApiBudget.objects.using(alias).filter(day__gte=now.date()-timedelta(days=7))
                                        .order_by("day").values("day", "used", "received", "inserted", "updated")), rules=[])
            for rule in rules:
                job = jobs.get(rule.pk)
                row = dict(kind=rule.kind, value=rule.value, name=rule.name, active=rule.active, stored=rule.stored,
                           retained_stored=Notice.objects.using(alias).filter(rules=rule, posted_at__gte=retention_start(now)).count(),
                           oldest_stored=rule.oldest, newest_stored=rule.newest)
                if job:
                    row.update(status=job.status, error_code=job.error_code, last_success_at=job.last_success_at,
                               backfill_cursor=job.backfill_cursor, backfill_end=job.backfill_end,
                               backfill_complete=job.backfill_status == "BACKFILL_COMPLETE",
                               backfill_status=job.backfill_status if rule.active else "PAUSED",
                               backfill_start=job.backfill_start or retention_start(job.backfill_end),
                               last_incremental_success=job.last_incremental_success,
                               local_matched=job.local_matched,
                               backfill_page=lane_stats(job.backfill_progress),
                               backfill_error=job.backfill_progress.get("last_error", ""),
                               incremental_error=job.incremental_progress.get("last_error", ""),
                               next_backfill_window=recent_backfill_window(job, now),
                               live_cursor=job.live_cursor, due_at=job.due_at, requested=job.requested,
                               progress={k: v for k, v in job.progress.items() if k not in {"completed_keys", "api_page_cache", "outcomes"}},
                               pending_api_queries=[dict(operation=q["operation"], numOfRows=q["numOfRows"],
                                                         totalCount=q["totalCount"], complete=q["complete"],
                                                         next_page=len(q["pages"])+1,
                                                         received=sum(p["received"] for p in q["pages"]))
                                                    for q in job.progress.get("api_page_cache", {}).values()])
                result["rules"].append(row)
            totals = {str(row["rule"].pk): row["totals"] for row in snapshot()["rows"]}
            for rule, row in zip(rules, result["rules"]):
                row["verified_window_totals"] = totals.get(str(rule.pk), {})
        self.stdout.write(json.dumps(result, cls=DjangoJSONEncoder, ensure_ascii=False))
