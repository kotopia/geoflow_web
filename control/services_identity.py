# control/services_identity.py
from typing import Optional
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

def ensure_user_from_request(request) -> Optional[str]:
    """
    auth_user 로 로그인한 사용자를 users에 연결/생성하고 UUID 반환.
    전략 순서:
      1) auth_user.email이 있으면 email로 매핑/생성
      2) email이 없으면 auth_user.id를 legacy_id로 매핑/생성
      3) email이 없지만 username이 이메일형식이면 그걸로 생성
    """
    user = getattr(request, "user", None)
    if not user or not user.is_authenticated:
        return None

    # 1) email로 시도
    email = getattr(user, "email", None) or None
    if email:
        uid = _fetch_user_id_by_email(email)
        if uid: 
            return uid
        # 없으면 생성
        with connections["default"].cursor() as cur:
            cur.execute(
                "INSERT INTO users(email, password_hash, is_active, legacy_id) "
                "VALUES (%s,'!',TRUE,%s) RETURNING id::text",
                [email, str(getattr(user, 'id', ''))]
            )
            return cur.fetchone()[0]

    # 2) legacy_id(auth_user.id)로 시도
    legacy_id = str(getattr(user, "id", "")) or None
    if legacy_id:
        uid = _fetch_user_id_by_legacy_id(legacy_id)
        if uid:
            return uid

    # 3) username이 이메일형식이면 생성
    username = getattr(user, "username", None)
    if username and "@" in username:
        with connections["default"].cursor() as cur:
            cur.execute(
                "INSERT INTO users(email, password_hash, is_active, legacy_id) "
                "VALUES (%s,'!',TRUE,%s) RETURNING id::text",
                [username, str(getattr(user, 'id', ''))]
            )
            return cur.fetchone()[0]

    return None

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
    with connections["default"].cursor() as cur:
        # 허용 도메인 자동승인
        cur.execute("SELECT allowed_domains FROM groups WHERE id=%s", [group_id])
        domains = [d.lower() for d in (cur.fetchone() or ([],))[0]]
        cur.execute("SELECT email FROM users WHERE id=%s", [user_id])
        email = (cur.fetchone() or [""])[0]
        dom = email.split("@", 1)[1].lower() if "@" in email else ""

        if dom in domains:
            cur.execute("""
              INSERT INTO user_group_map(id, user_id, group_id, role_id, status, created_at, updated_at)
              VALUES (gen_random_uuid(), %s, %s, %s, 'active', now(), now())
              ON CONFLICT (user_id, group_id)
              DO UPDATE SET role_id=EXCLUDED.role_id, status='active', updated_at=now()
            """, [user_id, group_id, viewer_role_id])
            return "auto_approved"
        else:
            cur.execute("""
              INSERT INTO join_requests(id, user_id, group_id, status, created_at)
              VALUES (gen_random_uuid(), %s, %s, 'pending', now())
              ON CONFLICT (user_id, group_id)
              DO UPDATE SET status='pending', decided_at=NULL, created_at=now()
            """, [user_id, group_id])
            return "pending"
