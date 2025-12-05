from django import template
from control.middleware import current_db_alias
from control.services_acl import user_has_perm
from control.services_identity import ensure_user_from_request, to_group_uuid

register = template.Library()

@register.simple_tag(takes_context=True)
def has_perm(context, perm_code):
    """
    템플릿에서 {% has_perm 'people.manage' as can_manage %} 로 사용.
    - auth_user.id(정수) → users.id(UUID) 로 정규화
    - 세션 group_id → groups.id(UUID) 로 정규화
    """
    req = context.get("request")
    if not req:
        return False

    # ✅ 1) 로그인 사용자를  UUID로 보장
    #    (없으면 users에 생성 후 UUID 반환)
    user_uuid = getattr(req, "_user_uuid", None)
    if not user_uuid:
        user_uuid = ensure_user_from_request(req)
        setattr(req, "_user_uuid", user_uuid)  # 페이지 내 다회 호출 캐시

    # ✅ 2) 세션의 group_id를  UUID로 정규화
    gid_raw = current_db_alias()
    group_uuid = to_group_uuid(gid_raw)

    # ✅ 3) 권한 조회
    return bool(user_uuid and group_uuid and user_has_perm(user_uuid, group_uuid, perm_code))
