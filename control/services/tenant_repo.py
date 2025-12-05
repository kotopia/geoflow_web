# control/services/tenant_repo.py
from __future__ import annotations

import logging
from typing import Optional

from django.db import connections, transaction

log = logging.getLogger(__name__)

def set_employee_role(tenant_alias: str, email: str, role_code: str) -> int:
    """
    테넌트의 hr.employee_profile에 role_code를 동기화한다.
    반환: 영향 행 수(없으면 0). 존재하지 않으면 0을 돌려주고 호출측에서 생성 여부 판단.
    """
    if not email or not role_code:
        return 0
    with transaction.atomic(using=tenant_alias):
        with connections[tenant_alias].cursor() as cur:
            cur.execute(
                """
                UPDATE hr.employee_profile
                   SET role_code=%s, updated_at=now()
                 WHERE lower(email)=lower(%s)
                """,
                [role_code, email],
            )
            return cur.rowcount

def ensure_employee(
    tenant_alias: str,
    email: str,
    name: Optional[str] = None,
    role_code: Optional[str] = None,
) -> None:
    """
    (선택) 직원 레코드가 없으면 최소 필드로 생성.
    프로젝트마다 스키마가 다를 수 있어 컬럼 존재 여부로 분기.
    """
    if not email:
        return
    with connections[tenant_alias].cursor() as cur:
        # 존재 여부
        cur.execute(
            "SELECT 1 FROM hr.employee_profile WHERE lower(email)=lower(%s) LIMIT 1",
            [email],
        )
        if cur.fetchone():
            return

    # 컬럼 존재 체크
    def has_col(col: str) -> bool:
        with connections[tenant_alias].cursor() as c2:
            c2.execute("""
                SELECT 1
                  FROM information_schema.columns
                 WHERE table_schema='hr' AND table_name='employee_profile' AND column_name=%s
                 LIMIT 1
            """, [col])
            return c2.fetchone() is not None

    cols = ["email"]
    vals = ["%s"]
    params = [email]
    if has_col("name") and name is not None:
        cols += ["name"]
        vals += ["%s"]
        params += [name]
    if has_col("role_code") and role_code is not None:
        cols += ["role_code"]
        vals += ["%s"]
        params += [role_code]

    sql = f"INSERT INTO hr.employee_profile ({', '.join(cols)}) VALUES ({', '.join(vals)})"
    with transaction.atomic(using=tenant_alias):
        with connections[tenant_alias].cursor() as cur3:
            cur3.execute(sql, params)

def upsert_employee_role(tenant_alias: str, email: str, role_code: str) -> None:
    """
    편의 함수: 업데이트가 0행이면 ensure + set 순서로 보장.
    """
    updated = set_employee_role(tenant_alias, email, role_code)
    if updated == 0:
        # 없으면 생성 후 다시 업데이트 시도
        ensure_employee(tenant_alias, email=email, role_code=role_code)
        set_employee_role(tenant_alias, email, role_code)
