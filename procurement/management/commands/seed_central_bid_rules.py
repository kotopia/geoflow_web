import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from procurement.models import CollectionRule
from procurement.service import central_alias, enqueue_rule


class Command(BaseCommand):
    help = "검토된 초기 중앙 수집조건을 추가합니다. 기존 이름/활성 상태는 유지합니다."

    def add_arguments(self, parser):
        parser.add_argument("--file", required=True)
        parser.add_argument("--execute", action="store_true")

    def handle(self, **options):
        try:
            rows = json.loads(Path(options["file"]).read_text())
            if not isinstance(rows, list) or not 1 <= len(rows) <= 100:
                raise ValueError()
            for row in rows:
                if not isinstance(row, dict) or set(row) != {"kind", "value", "name"}:
                    raise ValueError()
                if row["kind"] not in {"industry", "keyword"}:
                    raise ValueError()
                for field, size in (("value", 120), ("name", 255)):
                    if not isinstance(row[field], str) or not row[field].strip() or len(row[field]) > size:
                        raise ValueError()
                    row[field] = row[field].strip()
                if row["kind"] == "industry" and not (row["value"].isascii() and row["value"].isdigit()):
                    raise ValueError()
        except (OSError, ValueError, TypeError):
            raise CommandError("초기 수집조건 파일 형식을 확인하세요.") from None
        if not options["execute"]:
            self.stdout.write(f"Validated rules: {len(rows)}; no changes")
            return
        created_count = 0
        with transaction.atomic(using=central_alias()):
            for row in rows:
                rule, created = CollectionRule.objects.using(central_alias()).get_or_create(
                    kind=row["kind"], value=row["value"], defaults={"name": row["name"]})
                if created:
                    enqueue_rule(rule)
                    created_count += 1
        self.stdout.write(f"Created rules: {created_count}; existing rules preserved")
