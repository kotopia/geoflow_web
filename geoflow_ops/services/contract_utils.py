import re
from django.db import connections, transaction
from django.utils import timezone

CODE_RE = re.compile(r"^(\d{4})-(\d{3,4})$")

def next_contract_code(using_alias: str, width: int = 3) -> str:
    year = timezone.localdate().year
    lock_key = hash((using_alias, "contracts_code", year)) & 0x7FFFFFFF

    with transaction.atomic(using=using_alias):
        with connections[using_alias].cursor() as cur:
            # 연도별 직렬화
            cur.execute("SELECT pg_advisory_lock(%s);", [lock_key])

            # 현재 최대 번호 조회
            cur.execute("""
                SELECT code FROM contracts
                WHERE code LIKE %s
                ORDER BY code DESC
                LIMIT 1
            """, [f"{year}-%"])
            row = cur.fetchone()
            if row and row[0]:
                m = CODE_RE.match(row[0])
                n = int(m.group(2)) + 1 if m else 1
            else:
                n = 1
            code = f"{year}-{n:0{width}d}"

            cur.execute("SELECT pg_advisory_unlock(%s);", [lock_key])

    return code
