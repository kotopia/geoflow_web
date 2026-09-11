from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from procurement.models import Notice
from procurement.policy import retention_start
from procurement.service import central_alias, worker_lock


class Command(BaseCommand):
    help = "공고게시일 기준 2년 초과 공용 원본 정리. 기본 동작은 건수 확인뿐입니다."

    def add_arguments(self, parser):
        parser.add_argument("--execute", action="store_true")

    def handle(self, **options):
        cutoff = retention_start(timezone.now())
        with worker_lock() as acquired:
            if not acquired:
                raise CommandError("수집작업 진행 중입니다.")
            rows = Notice.objects.using(central_alias()).filter(posted_at__lt=cutoff)
            self.stdout.write(f"Expired notices: {rows.count()}; cutoff={cutoff.isoformat()}")
            if options["execute"]:
                # Tenant reviews hold independent references and are never cascaded.
                while True:
                    ids = list(rows.values_list("pk", flat=True)[:500])
                    if not ids:
                        break
                    Notice.objects.using(central_alias()).filter(pk__in=ids).delete()
