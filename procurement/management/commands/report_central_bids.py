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
                          total=Notice.objects.using(alias).count(),
                          retained_total=Notice.objects.using(alias).filter(posted_at__gte=retention_start(now)).count(),
                          daily_budget=getattr(settings, "G2B_CENTRAL_DAILY_BUDGET", 500),
                          api_days=list(ApiBudget.objects.using(alias).filter(day__gte=now.date()-timedelta(days=7))
                                        .order_by("day").values("day", "used")), rules=[])
            for rule in rules:
                job = jobs.get(rule.pk)
                row = dict(kind=rule.kind, value=rule.value, active=rule.active, stored=rule.stored,
                           oldest_stored=rule.oldest, newest_stored=rule.newest)
                if job:
                    row.update(status=job.status, error_code=job.error_code, last_success_at=job.last_success_at,
                               backfill_cursor=job.backfill_cursor, backfill_end=job.backfill_end,
                               backfill_complete=job.backfill_cursor >= job.backfill_end,
                               remaining_from=max(job.backfill_cursor, retention_start(now)),
                               live_cursor=job.live_cursor, due_at=job.due_at, requested=job.requested,
                               progress={k: v for k, v in job.progress.items() if k != "completed_keys"})
                result["rules"].append(row)
        self.stdout.write(json.dumps(result, cls=DjangoJSONEncoder, ensure_ascii=False))
