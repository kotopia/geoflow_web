# control/services/central_repo.py
from __future__ import annotations

import logging
from typing import Optional, Dict, Any, List, Tuple

from django.conf import settings
from django.db import connections, transaction

log = logging.getLogger(__name__)

# -------------------------------------------------------------------
# Helpers
# -------------------------------------------------------------------

def _central_alias() -> str:
    return getattr(settings, "CENTRAL_DB_ALIAS", "default")

def _default_tenant_alias() -> str:
    return getattr(settings, "DEFAULT_TENANT_DB_ALIAS", "default")

def _table_exists(alias: str, table: str) -> bool:
    with connections[alias].cursor() as cur:
        cur.execute("SELECT to_regclass(%s)", [f"public.{table}"])
        return bool(cur.fetchone()[0])

def _column_exists(alias: str, table: str, column: str) -> bool:
    with connections[alias].cursor() as cur:
        cur.execute("""
            SELECT 1
              FROM information_schema.columns
             WHERE table_schema='public' AND table_name=%s AND column_name=%s
             LIMIT 1
        """, [table, column])
        return cur.fetchone() is not None

def _dictfetchall(cur) -> List[Dict[str, Any]]:
    cols = [c[0] for c in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


# -------------------------------------------------------------------
# 중앙 --->테넌트 매핑
# -------------------------------------------------------------------
def get_tenant_by_host(host: str) -> dict | None:
    host = (host or "").split(":")[0].lower().strip()
    with connections[_central_alias()].cursor() as cur:
        cur.execute("""
            SELECT id::text, code, name, db_alias
            FROM tenants_v
            WHERE %s = ANY(SELECT lower(unnest(hostnames)))
            LIMIT 1
        """, [host])
        row = cur.fetchone()
        return {"id": row[0], "code": row[1], "name": row[2], "db_alias": row[3]} if row else None

def list_tenants_for_user(user_id: str) -> list[dict]:
    with connections[_central_alias()].cursor() as cur:
        cur.execute("""
            SELECT g.id::text, g.code, g.name, c.db_alias
            FROM user_group_map ug
            JOIN groups g          ON g.id = ug.group_id
            LEFT JOIN group_db_config c ON c.group_id = g.id
            WHERE ug.user_id = %s
            ORDER BY g.name
        """, [user_id])
        return [{"id": r[0], "code": r[1], "name": r[2], "db_alias": r[3]} for r in cur.fetchall()]


# -------------------------------------------------------------------
# Roles / Users
# -------------------------------------------------------------------

def get_role_id_by_code(code: str) -> Optional[str]:
    """roles.code → roles.id"""
    if not code:
        return None
    with connections[_central_alias()].cursor() as cur:
        cur.execute("SELECT id::text FROM roles WHERE code=%s LIMIT 1", [code])
        row = cur.fetchone()
        return row[0] if row else None

def get_user_by_email(email: str) -> Optional[Dict[str, Any]]:
    if not email:
        return None
    with connections[_central_alias()].cursor() as cur:
        cur.execute(
            "SELECT id::text AS id, email FROM users WHERE lower(email)=lower(%s) LIMIT 1",
            [email],
        )
        row = cur.fetchone()
        if not row:
            return None
        return {"id": row[0], "email": row[1]}

def create_user(email: str, name: Optional[str] = None) -> str:
    """최소 필드로 사용자 생성. 이미 있으면 기존 id 반환."""
    with transaction.atomic(using=_central_alias()):
        with connections[_central_alias()].cursor() as cur:
            cur.execute(
                """
                INSERT INTO users (id, email, name, created_at, updated_at)
                SELECT gen_random_uuid(), %s, %s, now(), now()
                WHERE NOT EXISTS (
                    SELECT 1 FROM users WHERE lower(email)=lower(%s)
                )
                RETURNING id::text
                """,
                [email, name or "", email],
            )
            row = cur.fetchone()
            if row:
                return row[0]
        # 이미 있었던 케이스 → id 재조회
        with connections[_central_alias()].cursor() as cur2:
            cur2.execute(
                "SELECT id::text FROM users WHERE lower(email)=lower(%s) LIMIT 1",
                [email],
            )
            return cur2.fetchone()[0]

def get_or_create_user_by_email(email: str, name: Optional[str] = None) -> str:
    found = get_user_by_email(email)
    return found["id"] if found else create_user(email, name=name)

# -------------------------------------------------------------------
# Group membership (user_group_map 표준)
# -------------------------------------------------------------------

def upsert_user_group_membership(
    user_id: str, group_id: str, role_id: str, status: str = "active"
) -> None:
    with transaction.atomic(using=_central_alias()):
        with connections[_central_alias()].cursor() as cur:
            cur.execute(
                """
                INSERT INTO user_group_map (id, user_id, group_id, role_id, status, created_at, updated_at)
                VALUES (gen_random_uuid(), %s, %s, %s, %s, now(), now())
                ON CONFLICT (user_id, group_id)
                DO UPDATE SET role_id=EXCLUDED.role_id, status=%s, updated_at=now()
                """,
                [user_id, group_id, role_id, status, status],
            )

# -------------------------------------------------------------------
# Join Requests
# -------------------------------------------------------------------

def get_join_request(req_id: str) -> Optional[Dict[str, Any]]:
    with connections[_central_alias()].cursor() as cur:
        cur.execute(
            """
            SELECT
                jr.id::text      AS id,
                jr.user_id::text AS requester_user_id,
                jr.group_id::text AS group_id,
                jr.requested_email,
                jr.requested_role_code,
                jr.status,
                jr.created_at
            FROM join_requests jr
            WHERE jr.id = %s
            LIMIT 1
            """,
            [str(req_id)],
        )
        row = cur.fetchone()
        if not row:
            return None
        return {
            "id": row[0],
            "requester_user_id": row[1],
            "group_id": row[2],
            "requested_email": row[3],
            "requested_role_code": row[4],
            "status": row[5],
            "created_at": row[6],
        }

def mark_join_request_status(req_id: str, status: str, decided_by: Optional[str] = None):
    with connections[_central_alias()].cursor() as cur:
        if _column_exists(_central_alias(), "join_requests", "decided_by"):
            cur.execute("""
                UPDATE join_requests
                   SET status=%s,
                       decided_by=%s,
                       decided_at=now(),
                       updated_at=now()
                 WHERE id=%s
            """, [status, decided_by, req_id])
        else:
            cur.execute("""
                UPDATE join_requests
                   SET status=%s,
                       updated_at=now()
                 WHERE id=%s
            """, [status, req_id])

def list_pending_join_requests() -> List[Dict[str, Any]]:
    with connections[_central_alias()].cursor() as cur:
        cur.execute(
            """
            SELECT
                jr.id::text                AS id,
                u.email                    AS requester_email,
                jr.requested_email         AS target_email,
                g.name                     AS group_name,
                g.code                     AS group_code,
                jr.requested_role_code     AS role_code,
                jr.created_at              AS created_at
            FROM join_requests jr
            LEFT JOIN users  u ON u.id  = jr.user_id
            LEFT JOIN groups g ON g.id  = jr.group_id
            WHERE jr.status='pending'
            ORDER BY jr.created_at DESC
            """
        )
        rows = cur.fetchall()
    return [
        {
            "id": r[0],
            "requester_email": r[1] or "-",
            "target_email": r[2] or "-",
            "group_name": r[3],
            "group_code": r[4],
            "role_code": r[5],
            "created_at": r[6],
        }
        for r in rows
    ]

# -------------------------------------------------------------------
# Groups Admin (목록 7-튜플로 반환: id, code, name, status, domains, owner_email, db_alias)
# -------------------------------------------------------------------

def _group_owner_join_sql(alias: str) -> Tuple[str, bool]:
    """groups.owner_user_id 컬럼이 있으면 join, 없으면 owner는 NULL"""
    has_owner = _column_exists(alias, "groups", "owner_user_id")
    if has_owner:
        return (
            """
            SELECT g.id::text, g.code, g.name, g.status, g.allowed_domains, u.email AS owner_email
              FROM groups g
              LEFT JOIN users u ON u.id = g.owner_user_id
            """,
            True,
        )
    else:
        return (
            """
            SELECT g.id::text, g.code, g.name, g.status, g.allowed_domains, NULL::text AS owner_email
              FROM groups g
            """,
            False,
        )

def resolve_group_db_alias(group_id: Optional[str] = None, group_code: Optional[str] = None) -> str:
    """
    그룹별 테넌트 DB alias를 결정한다.
    우선순위:
      1) groups.db_alias 컬럼 (있다면)
      2) group_db_config 테이블 매핑 (있다면)
      3) settings.TENANT_DB_ALIAS_MAP dict (있다면)  ex) {'cheonan': 'cheonan_db'}
      4) settings.DATABASES 키에 f'{group_code}_db'가 있으면 그걸 사용
      5) DEFAULT_TENANT_DB_ALIAS
    """
    alias = _central_alias()

    # 1) groups.db_alias
    if group_id and _column_exists(alias, "groups", "db_alias"):
        with connections[alias].cursor() as cur:
            cur.execute("SELECT db_alias FROM groups WHERE id=%s LIMIT 1", [group_id])
            r = cur.fetchone()
            if r and r[0] and r[0] in settings.DATABASES:
                return r[0]

    # group_code 조회 필요 시
    if not group_code and group_id:
        with connections[alias].cursor() as cur:
            cur.execute("SELECT code FROM groups WHERE id=%s LIMIT 1", [group_id])
            r = cur.fetchone()
            group_code = r[0] if r else None

    # 2) group_db_config
    if group_id and _table_exists(alias, "group_db_config"):
        with connections[alias].cursor() as cur:
            cur.execute("SELECT db_alias FROM group_db_config WHERE group_id=%s LIMIT 1", [group_id])
            r = cur.fetchone()
            if r and r[0] and r[0] in settings.DATABASES:
                return r[0]

    # 3) settings map
    m: Dict[str, str] = getattr(settings, "TENANT_DB_ALIAS_MAP", {})
    if group_code and m.get(group_code) in settings.DATABASES:
        return m[group_code]

    # 4) {code}_db
    if group_code:
        candidate = f"{group_code}_db"
        if candidate in settings.DATABASES:
            return candidate

    # 5) fallback
    return _default_tenant_alias()

def list_groups_admin() -> List[Tuple[str, str, str, str, Optional[str], Optional[str], str]]:
    """
    템플릿이 7개 언패킹을 기대하므로 반드시 7-튜플로 반환:
    (id, code, name, status, allowed_domains, owner_email, db_alias)
    """
    alias = _central_alias()
    head_sql, _ = _group_owner_join_sql(alias)

    with connections[alias].cursor() as cur:
        cur.execute(head_sql + " ORDER BY g.created_at DESC NULLS LAST, g.name ASC")
        rows = cur.fetchall()

    result: List[Tuple[str, str, str, str, Optional[str], Optional[str], str]] = []
    for rid, code, name, status, domains, owner_email in rows:
        db_alias = resolve_group_db_alias(group_id=rid, group_code=code)
        result.append((rid, code, name, status, domains, owner_email, db_alias))
    return result

def add_or_update_join_request(user_id: str, group_id: str, requested_email: str, role_code: str) -> None:
    with connections[_central_alias()].cursor() as cur:
        cur.execute("""
            INSERT INTO join_requests
                (id, user_id, group_id, requested_email, requested_role_code, status, created_at, updated_at)
            VALUES (gen_random_uuid(), %s, %s, %s, %s, 'pending', now(), now())
            ON CONFLICT (user_id, group_id, requested_email)
            DO UPDATE SET
                requested_role_code = EXCLUDED.requested_role_code,
                status              = 'pending',
                updated_at          = now()
        """, [user_id, group_id, requested_email.strip().lower(), role_code])

def list_my_join_requests(user_id: str) -> list[dict]:
    with connections[_central_alias()].cursor() as cur:
        cur.execute("""
            SELECT
                jr.id::text          AS id,
                g.name               AS group_name,
                g.code               AS group_code,
                jr.requested_email   AS target_email,
                jr.requested_role_code AS role_code,
                jr.status            AS status,
                jr.created_at        AS created_at
            FROM join_requests jr
            LEFT JOIN groups g ON g.id = jr.group_id
            WHERE jr.user_id = %s
            ORDER BY jr.created_at DESC
        """, [user_id])
        rows = cur.fetchall()
    return [{
        "id": r[0], "group_name": r[1], "group_code": r[2],
        "target_email": r[3], "role_code": r[4],
        "status": r[5], "created_at": r[6],
    } for r in rows]

def role_code_for_email(group_id: str, email: str) -> str | None:
    if not email:
        return None
    with connections[_central_alias()].cursor() as cur:
        cur.execute("""
            SELECT r.code
              FROM user_group_map ugm
              JOIN users u ON u.id = ugm.user_id
              JOIN roles r ON r.id = ugm.role_id
             WHERE ugm.group_id = %s
               AND ugm.status   = 'active'
               AND lower(u.email) = lower(%s)
             LIMIT 1
        """, [group_id, email])
        row = cur.fetchone()
        return row[0] if row else None

def roles_by_email_for_group(group_id: str, emails: list[str]) -> dict[str, str]:
    if not emails:
        return {}
    lowered = [ (e or "").strip().lower() for e in emails if e ]
    with connections[_central_alias()].cursor() as cur:
        cur.execute("""
            SELECT lower(u.email) AS email, r.code
              FROM user_group_map ugm
              JOIN users u ON u.id = ugm.user_id
              JOIN roles r ON r.id = ugm.role_id
             WHERE ugm.group_id = %s
               AND ugm.status   = 'active'
               AND lower(u.email) = ANY(%s)
        """, [group_id, lowered])
        rows = cur.fetchall()
    return { e: code for (e, code) in rows }

# def list_active_roles() -> list[dict]:
#     alias = _central_alias()
#     # 컬럼 유무에 따라 where/order를 안전하게 구성
#     has_status = _column_exists(alias, "roles", "status")
#     has_display = _column_exists(alias, "roles", "display_order")

#     where = "WHERE status='active'" if has_status else ""
#     order = "display_order NULLS LAST, name" if has_display else "name"

#     with connections[alias].cursor() as cur:
#         cur.execute(f"SELECT code, name FROM roles {where} ORDER BY {order}")
#         rows = cur.fetchall()
#     return [{"code": r[0], "name": r[1]} for r in rows]

def user_has_password(user_id: str) -> bool:
    alias = _central_alias()
    if not _column_exists(alias, "users", "password_hash"):
        return False
    with connections[alias].cursor() as cur:
        # 빈 문자열/공백도 비밀번호 없음으로 판단
        cur.execute("""
            SELECT (password_hash IS NOT NULL) AND (length(trim(password_hash)) > 0)
            FROM users
            WHERE id = %s
        """, [user_id])
        row = cur.fetchone()
        return bool(row and row[0])


import secrets
from datetime import timedelta
from django.utils import timezone

def create_set_password_token(user_id: str, ttl_minutes: int = 60*24) -> str:
    token = secrets.token_urlsafe(32)
    expires = timezone.now() + timedelta(minutes=ttl_minutes)
    with connections[_central_alias()].cursor() as cur:
        cur.execute("""
            INSERT INTO user_tokens (user_id, token, kind, expires_at, created_at)
            VALUES (%s, %s, 'set_password', %s, now())
        """, [user_id, token, expires])
    return token

def get_valid_token(token: str, kind: str) -> dict | None:
    with connections[_central_alias()].cursor() as cur:
        cur.execute("""
          SELECT id::text, user_id::text, kind, expires_at, used_at
            FROM user_tokens
           WHERE token=%s AND kind=%s AND used_at IS NULL AND now() < expires_at
           LIMIT 1
        """, [token, kind])
        row = cur.fetchone()
        if not row:
            return None
        return {"id": row[0], "user_id": row[1], "kind": row[2], "expires_at": row[3], "used_at": row[4]}

def mark_token_used(token: str) -> None:
    with connections[_central_alias()].cursor() as cur:
        cur.execute("UPDATE user_tokens SET used_at=now() WHERE token=%s", [token])

def set_user_password(user_id: str, password_hash: str) -> None:
    with connections[_central_alias()].cursor() as cur:
        if not _column_exists(_central_alias(), "users", "password_hash"):
            raise RuntimeError("users.password_hash 컬럼이 없습니다.")
        cur.execute("UPDATE users SET password_hash=%s, updated_at=now() WHERE id=%s", [password_hash, user_id])

def list_active_roles() -> list[dict]:
    alias = _central_alias()
    has_status = _column_exists(alias, "roles", "status")
    has_display = _column_exists(alias, "roles", "display_order")
    where = "WHERE status='active'" if has_status else ""
    order = "display_order NULLS LAST, name" if has_display else "name"
    with connections[alias].cursor() as cur:
        cur.execute(f"SELECT code, name FROM roles {where} ORDER BY {order}")
        rows = cur.fetchall()
    return [{"code": r[0], "name": r[1]} for r in rows]

from django.core.mail import send_mail

def send_set_password_email(to_email: str, link: str) -> None:
    subject = "[GeoFlow] 비밀번호 설정 안내"
    body = f"""안녕하세요.

GeoFlow에 접근하실 수 있도록 비밀번호 설정 링크를 보내드립니다.
아래 링크는 24시간 동안만 유효합니다.

{link}

본인이 요청하지 않은 경우 이 메일을 무시하셔도 됩니다.
"""
    send_mail(subject, body, getattr(settings, "DEFAULT_FROM_EMAIL", "no-reply@geoflow.local"), [to_email], fail_silently=False)
