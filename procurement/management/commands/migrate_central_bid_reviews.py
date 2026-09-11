"""Additive, idempotent migration; existing operational records are never deleted."""
from django.core.management.base import BaseCommand, CommandError
from django.db import connections, transaction

from procurement.policy import canonical_order, notice_id
from procurement.service import central_alias
from geoflow_ops.bids.sync import _detail_url


class Command(BaseCommand):
    help = "회사 입찰 검토기록의 중앙 공고 참조를 추가합니다. 기본은 읽기 전용 점검입니다."

    def add_arguments(self, parser):
        parser.add_argument("--database", required=True)
        parser.add_argument("--execute", action="store_true")

    def handle(self, **options):
        alias = options["database"]
        if alias == central_alias() or alias not in connections.databases:
            raise CommandError("명시적으로 등록된 회사 DB 연결이 필요합니다.")
        with connections[alias].cursor() as cur:
            cur.execute("""SELECT n.id::text,n.bid_notice_no,n.bid_notice_ord,n.title,n.detail_url,
                           r.status,COALESCE(r.memo,''),COALESCE(r.updated_by,''),r.updated_at
                           FROM bid.notice_reviews r JOIN bid.notices n ON n.id=r.notice_id
                           WHERE n.source='g2b' AND n.business_type='service' ORDER BY r.updated_at DESC""")
            rows = cur.fetchall()
        ids = [notice_id(row[1], row[2]) for row in rows]
        if len(set(ids)) != len(ids):
            raise CommandError("차수 정규화 후 검토기록 충돌이 있습니다. 자동 병합하지 않습니다.")
        self.stdout.write(f"Review records to map: {len(rows)}")
        if not options["execute"]:
            return
        with transaction.atomic(using=alias), connections[alias].cursor() as cur:
            for row in rows:
                cur.execute("""INSERT INTO bid.central_reviews
                  (central_notice_id,legacy_notice_id,notice_number,notice_order,title,detail_url,
                   status,memo,updated_by,updated_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                  ON CONFLICT(central_notice_id) DO NOTHING""",
                  [str(notice_id(row[1], row[2])), row[0], row[1], canonical_order(row[2]), row[3],
                   _detail_url(row[4]), *row[5:]])
