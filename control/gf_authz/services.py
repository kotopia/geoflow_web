from typing import Dict, List, Set, Optional
from django.conf import settings
from django.db import connections


def _table(name: str, default: str) -> str:
    return getattr(settings, "GF_AUTHZ_TABLES", {}).get(name, default)

def _central_alias() -> str:
    return getattr(settings, "GF_AUTHZ_CENTRAL_ALIAS", "default")

def _resolve_group_id(request) -> Optional[str]:
    """
    세션/미들웨어에서 저장한 현재 테넌트(그룹) id를 가져옵니다.
    프로젝트에서 실제 키 이름에 맞게 우선순위로 확인해 주세요.
    """
    for key in ("group_id", "group_uuid", "tenant_group_id", "tenant_id"):
        val = request.session.get(key)
        if val:
            return str(val)
    return None

def _resolve_central_user_uuid(cur, users_tbl: str, email: str) -> Optional[str]:
    cur.execute(f"SELECT id FROM {users_tbl} WHERE lower(email)=lower(%s) LIMIT 1", [email])
    row = cur.fetchone()
    return str(row[0]) if row else None


def gf_load_user_context(request) -> Dict:
    """
    중앙 DB에서 현재 로그인 사용자(email 기준)의 uuid를 찾고,
    해당 사용자@현재 그룹에서의 roles → permissions를 확장합니다.
    """
    alias = _central_alias()
    users_tbl            = _table("users",            "public.users")
    user_roles_tbl       = _table("user_roles",       "public.user_group_map")  # 매핑 사용
    roles_tbl            = _table("roles",            "public.roles")
    role_permissions_tbl = _table("role_permissions", "public.role_permissions")
    permissions_tbl      = _table("permissions",      "public.permissions")
    project_members_tbl  = _table("project_members",  "public.project_members")

    email = getattr(request.user, "email", None)
    group_id = _resolve_group_id(request)

    roles: Set[str] = set()
    perms: Set[str] = set()
    project_ids: List[str] = []

    with connections[alias].cursor() as cur:
        # 1) auth_user.id(int)이 아니라 중앙 users.id(uuid)로 변환
        central_user_id = _resolve_central_user_uuid(cur, users_tbl, email or "")
        if not central_user_id:
            return {"tenant_id": group_id, "roles": [], "perms": [], "project_ids": []}

        # 2) roles (그룹 스코프 적용)
        if group_id:
            cur.execute(f"""
                SELECT r.code
                  FROM {user_roles_tbl} ur
                  JOIN {roles_tbl} r ON r.id = ur.role_id
                 WHERE ur.user_id = %s
                   AND ur.group_id = %s
                   AND (ur.status IS NULL OR ur.status='active')
            """, [central_user_id, group_id])
        else:
            cur.execute(f"""
                SELECT r.code
                  FROM {user_roles_tbl} ur
                  JOIN {roles_tbl} r ON r.id = ur.role_id
                 WHERE ur.user_id = %s
                   AND (ur.status IS NULL OR ur.status='active')
            """, [central_user_id])
        roles = {row[0] for row in cur.fetchall()}

        # 3) perms (역할→퍼미션 확장, 동일 스코프)
        if roles:
            if group_id:
                cur.execute(f"""
                    SELECT DISTINCT p.code
                      FROM {user_roles_tbl} ur
                      JOIN {role_permissions_tbl} rp ON rp.role_id = ur.role_id
                      JOIN {permissions_tbl}      p ON p.id = rp.permission_id
                     WHERE ur.user_id = %s
                       AND ur.group_id = %s
                       AND (ur.status IS NULL OR ur.status='active')
                """, [central_user_id, group_id])
            else:
                cur.execute(f"""
                    SELECT DISTINCT p.code
                      FROM {user_roles_tbl} ur
                      JOIN {role_permissions_tbl} rp ON rp.role_id = ur.role_id
                      JOIN {permissions_tbl}      p ON p.id = rp.permission_id
                     WHERE ur.user_id = %s
                       AND (ur.status IS NULL OR ur.status='active')
                """, [central_user_id])
            perms = {row[0] for row in cur.fetchall()}

        # 4) 프로젝트 스코프(선택)
        if project_members_tbl in getattr(settings, "GF_AUTHZ_TABLES", {}):
            cur.execute(f"""
                SELECT pm.project_id
                  FROM {project_members_tbl} pm
                 WHERE pm.user_id = %s
            """, [central_user_id])
            project_ids = [row[0] for row in cur.fetchall()]

    return {"tenant_id": group_id, "roles": list(roles), "perms": list(perms), "project_ids": project_ids}
