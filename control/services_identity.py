# control/services_identity.py
from typing import Optional
from django.conf import settings
from django.db import connections

def _fetch_user_id_by_email(email: str) -> Optional[str]:
    if not email:
        return None
    with connections["default"].cursor() as cur:
        cur.execute("SELECT id::text FROM users WHERE email=%s LIMIT 1", [email])
        row = cur.fetchone()
        return row[0] if row else None

def _fetch_user_id_by_legacy_id(legacy_id: str) -> Optional[str]:
    if not legacy_id:
        return None
    with connections["default"].cursor() as cur:
        cur.execute("SELECT id::text FROM users WHERE legacy_id=%s LIMIT 1", [legacy_id])
        row = cur.fetchone()
        return row[0] if row else None


def lookup_user_id_from_request(request) -> Optional[str]:
    """Return an existing central user id without creating any account."""
    user = getattr(request, "user", None)
    if not user or not user.is_authenticated:
        return None

    identity = (
        getattr(user, "email", None)
        or getattr(user, "username", None)
        or ""
    ).strip().lower()
    if not identity:
        return None

    central_alias = getattr(settings, "CENTRAL_DB_ALIAS", "default")
    with connections[central_alias].cursor() as cur:
        cur.execute(
            "SELECT id::text FROM users "
            "WHERE lower(email)=lower(%s) LIMIT 1",
            [identity],
        )
        row = cur.fetchone()
    return row[0] if row else None


def ensure_user_from_request(request) -> Optional[str]:
    """Disabled legacy helper retained only to fail closed for stale callers.

    Central identities must be created through the explicit signup/admin lifecycle.
    Authentication or a Django session bridge must never provision or activate a
    central account implicitly.
    """
    raise RuntimeError("Legacy implicit central account provisioning is disabled")


def to_group_uuid(group_any) -> Optional[str]:
    """
    세션에서 온 값이 정수(레거시 PK)거나 code거나 이미 UUID인 경우 모두
    groups.id(UUID) 문자열로 변환.
    """
    if not group_any:
        return None
    s = str(group_any)

    # 이미 UUID 형태면 그대로
    if len(s) == 36 and s.count("-") == 4:
        return s

    with connections["default"].cursor() as cur:
        # id::text / code / legacy_id 중 무엇으로든 매칭
        cur.execute("""
            SELECT id::text
              FROM groups
             WHERE id::text = %s OR code = %s OR legacy_id = %s
             LIMIT 1
        """, [s, s, s])
        row = cur.fetchone()
        return row[0] if row else None
    
def get_or_create_user_by_email(email: str):
    """Legacy invitation helper: create only an inactive, unverified placeholder."""
    with connections["default"].cursor() as cur:
        cur.execute("SELECT id FROM users WHERE email=%s", [email])
        row = cur.fetchone()
        if row:
            return row[0], False
        cur.execute("""
            INSERT INTO users(id, email, is_active, email_verified, created_at, updated_at)
            VALUES (gen_random_uuid(), %s, FALSE, FALSE, now(), now())
            RETURNING id
        """, [email])
        return cur.fetchone()[0], True

def create_or_pending_membership(user_id, group_id, viewer_role_id):
    """Legacy invitation helper that can only create a pending join request.

    Domain matching must never activate membership automatically. Live approval is
    handled by the explicit central join approval service.
    """
    with connections["default"].cursor() as cur:
        cur.execute("""
          INSERT INTO join_requests(id, user_id, group_id, status, created_at)
          VALUES (gen_random_uuid(), %s, %s, 'pending', now())
          ON CONFLICT (user_id, group_id)
          DO UPDATE SET status='pending', decided_at=NULL, created_at=now()
        """, [user_id, group_id])
    return "pending"
