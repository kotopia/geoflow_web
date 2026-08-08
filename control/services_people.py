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
                                is_active: bool = False,
                                is_staff: bool = False) -> tuple[str, bool]:
    """Return an existing user or create only an inactive, unverified placeholder.

    Legacy people helpers must never create an active/staff central identity. Account
    activation belongs to the explicit verification and central approval lifecycle.
    """
    email = (email or "").strip().lower()
    if not email:
        raise ValueError("email required")
    if is_active or is_staff:
        raise RuntimeError("Legacy people provisioning cannot activate central accounts")

    with connections["default"].cursor() as cur:
        cur.execute("SELECT id::text FROM users WHERE lower(email)=lower(%s) LIMIT 1", [email])
        row = cur.fetchone()
        if row:
            return row[0], False

        cur.execute("""
            INSERT INTO users (id, email, is_active, is_staff, email_verified, created_at, updated_at)
            VALUES (gen_random_uuid(), %s, FALSE, FALSE, FALSE, now(), now())
            RETURNING id::text
        """, [email])
        new_id = cur.fetchone()[0]
        return new_id, True
