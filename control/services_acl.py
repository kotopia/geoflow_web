# control/services_acl.py
from django.db import connections

def user_has_perm(user_id: str, group_id: str, perm_code: str) -> bool:
    """
    그룹 단위 권한 평가 (최소 구현).
    - 조직단위/서브트리 도입 전까지는 이 함수로 충분합니다.
    - 확장 시: unit_uuid, scope('self'|'subtree')를 인자로 추가하고 SQL을 anc/desc 조인으로 늘리면 됩니다.
    """
    sql = """
    SELECT 1
      FROM user_group_map ugm
      JOIN role_permissions rp ON rp.role_id = ugm.role_id
      JOIN permissions p ON p.id = rp.permission_id
     WHERE ugm.user_id=%s
       AND ugm.group_id=%s
       AND ugm.status='active'
       AND p.code=%s
     LIMIT 1
    """
    with connections["default"].cursor() as cur:
        cur.execute(sql, [user_id, group_id, perm_code])
        return cur.fetchone() is not None
