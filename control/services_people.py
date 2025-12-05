from typing import Tuple
from django.db import connections
from django.conf import settings
from control.models import GroupDBConfig

VIEW  = settings.TENANT_PROFILE_VIEW          # "people_profile"
TABLE = settings.TENANT_PROFILE_TABLE         # "hr.employee_profile"

def list_members(central_group_id, tenant_alias):
    with connections["default"].cursor() as cur:
        cur.execute("""
            SELECT u.id::text,
                   u.email,
                   COALESCE(r.code, '') AS role_code,
                   ugm.status AS member_status,
                   u.last_login
              FROM user_group_map ugm
              JOIN users u       ON u.id = ugm.user_id
              LEFT JOIN roles r  ON r.id = ugm.role_id
             WHERE ugm.group_id = %s AND ugm.status='active'
             ORDER BY u.email
        """, [central_group_id])
        rows = cur.fetchall()

    result = []
    with connections[tenant_alias].cursor() as tcur:
        for user_id, email, role_code, member_status, last_login in rows:
            tcur.execute(f"""
                SELECT name, phone, hire_date, title
                  FROM {VIEW}
                 WHERE user_id = %s
                 LIMIT 1
            """, [user_id])
            prow = tcur.fetchone()
            if prow:
                name, phone, hire_date, title = prow
            else:
                name = phone = title = None
                hire_date = None
            result.append({
                "user_id": user_id,
                "email": email,
                "role_code": role_code,
                "member_status": member_status,
                "last_login": last_login,
                "name": name, "phone": phone, "hire_date": hire_date, "title": title,
            })
    return result

def ensure_profile(tenant_alias, user_id, email, name=None):
    with connections[tenant_alias].cursor() as cur:
        cur.execute(f"""
            INSERT INTO {TABLE} (user_id, email, name, status, created_at, updated_at)
            VALUES (%s, %s, %s, 'active', now(), now())
            ON CONFLICT (user_id) DO UPDATE
                SET email = EXCLUDED.email,
                    name  = COALESCE(EXCLUDED.name, {TABLE}.name),
                    updated_at = now()
        """, [user_id, email, name])

def fetch_profile(tenant_alias, user_id):
    with connections[tenant_alias].cursor() as cur:
        cur.execute(f"""
            SELECT user_id::text, email, name, phone, hire_date, title, status
              FROM {VIEW}
             WHERE user_id = %s
             LIMIT 1
        """, [user_id])
        row = cur.fetchone()
    if not row:
        return None
    return {
        "user_id": row[0], "email": row[1], "name": row[2],
        "phone": row[3], "hire_date": row[4], "title": row[5], "status": row[6],
    }

def get_group_alias(group_id: str) -> str:
    cfg = GroupDBConfig.objects.using("default").get(group_id=group_id)
    return cfg.db_alias

def ensure_group_profile(user_id, group_id) -> None:
    alias = get_group_alias(group_id)
    with connections[alias].cursor() as cur:
        cur.execute(f"""
            INSERT INTO {TABLE} (user_id, status, created_at, updated_at)
            VALUES (%s, 'active', now(), now())
            ON CONFLICT (user_id) DO NOTHING
        """, [str(user_id)])

def get_group_profile(user_id, group_id):
    alias = get_group_alias(group_id)
    with connections[alias].cursor() as cur:
        cur.execute(f"""
            SELECT email, name, phone, hire_date, title, status
              FROM {VIEW}
             WHERE user_id = %s
             LIMIT 1
        """, [str(user_id)])
        row = cur.fetchone()
        if not row:
            return None
        return {
            "email": row[0], "name": row[1], "phone": row[2],
            "hire_date": row[3], "title": row[4], "status": row[5],
        }

def get_or_create_user_by_email(email: str,
                                *,
                                is_active: bool = True,
                                is_staff: bool = False) -> tuple[str, bool]:
    """
    중앙 DB(users)에 email 기준으로 사용자를 조회하고,
    없으면 stub 계정(비밀번호 없음)으로 생성한다.
    return: (user_id, created)
    """
    email = (email or "").strip().lower()
    if not email:
        raise ValueError("email required")

    with connections["default"].cursor() as cur:
        # 1) 존재 확인 (citext라도 lower 비교로 안전하게)
        cur.execute("SELECT id::text FROM users WHERE lower(email)=lower(%s) LIMIT 1", [email])
        row = cur.fetchone()
        if row:
            return row[0], False

        # 2) 없으면 생성 (비밀번호는 NULL, 이메일 미인증)
        cur.execute("""
            INSERT INTO users (id, email, is_active, is_staff, email_verified, created_at, updated_at)
            VALUES (gen_random_uuid(), %s, %s, %s, FALSE, now(), now())
            RETURNING id::text
        """, [email, is_active, is_staff])
        new_id = cur.fetchone()[0]
        return new_id, True