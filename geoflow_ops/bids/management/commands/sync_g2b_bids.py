from __future__ import annotations

from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connections
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from geoflow_ops.bids.sync import sync_service_notices


class Command(BaseCommand):
    help = "명시한 테넌트 DB에 나라장터 용역 입찰공고를 동기화합니다."

    def add_arguments(self, parser):
        parser.add_argument("--database", required=True, help="동기화할 테넌트 DB 별칭")
        parser.add_argument("--days", type=int, default=2, help="현재부터 과거 조회 일수(1~7)")
        parser.add_argument("--start", help="ISO-8601 조회 시작시각")
        parser.add_argument("--end", help="ISO-8601 조회 종료시각")

    def handle(self, *args, **options):
        alias = str(options["database"] or "").strip()
        if alias == getattr(settings, "CENTRAL_DB_ALIAS", "default") or alias not in connections.databases:
            raise CommandError("등록된 테넌트 DB 별칭을 --database로 지정하세요.")
        end = parse_datetime(options.get("end") or "") or timezone.now()
        start = parse_datetime(options.get("start") or "")
        if start is None:
            days = min(max(int(options.get("days") or 2), 1), 7)
            start = end - timedelta(days=days)
        result = sync_service_notices(alias, start, end)
        self.stdout.write(self.style.SUCCESS(
            "G2B sync completed: "
            f"fetched={result['fetched']} inserted={result['inserted']} "
            f"updated={result['updated']} matched={result['matched']}"
        ))
