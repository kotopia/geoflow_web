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
        if options["execute"]:
            raise CommandError("업무기록 참조 보존정책 검증 전에는 원본을 물리 삭제하지 않습니다. --execute 없이 만료 건수를 확인하세요.")
        cutoff = retention_start(timezone.now())
        with worker_lock() as acquired:
            if not acquired:
                raise CommandError("수집작업 진행 중입니다.")
            rows = Notice.objects.using(central_alias()).filter(posted_at__lt=cutoff)
            self.stdout.write(f"Expired notices: {rows.count()}; cutoff={cutoff.isoformat()}")
