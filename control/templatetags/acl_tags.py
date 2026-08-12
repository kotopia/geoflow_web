from django import template
from django.conf import settings

from control.services import central_repo as C
from control.services_identity import lookup_user_id_from_request

register = template.Library()

# 화면에서 쓰는 추상 권한 → 실제 중앙 코드(들)
PERM_ALIASES = {
    "people.manage": {"directory.edit", "projects.edit"},  # 직원 편집/생성은 중앙의 편집권한으로도 허용
    # 필요 시 추가: "maps.manage": {"maps.edit", "maps.publish"},
}

def _norm(code: str) -> set[str]:
    if not code:
        return set()
    if code in PERM_ALIASES:
        return {code, *PERM_ALIASES[code]}
    return {code}


def _tenant_scope_is_active(request) -> bool:
    """Legacy ACL checks are valid only inside an explicit tenant request."""
    central_alias = str(
        getattr(settings, "CENTRAL_DB_ALIAS", "default") or "default"
    ).strip()
    tenant_alias = str(request.session.get("tenant_db_alias") or "").strip()
    scope = str(request.session.get("scope") or "").strip().lower()
    return bool(tenant_alias and tenant_alias != central_alias and scope == "tenant")


@register.simple_tag(takes_context=True)
def has_perm(context, perm_code: str) -> bool:
    req = context.get("request")
    if not req or not _tenant_scope_is_active(req):
        return False

    needed = _norm(perm_code)

    # GFAuthzContextMiddleware가 설정한 요청 단위 캐시는 현재 요청의 authoritative
    # 권한 상태다. 빈 set()도 명시적인 권한 없음이므로 legacy session cache로
    # 되돌아가면 안 된다.
    request_perms = getattr(req, "_gf_perms_cache", None)
    if request_perms is not None:
        return bool(set(request_perms) & needed)

    user_uuid = getattr(req, "_user_uuid", None) or lookup_user_id_from_request(req)
    group_id = req.session.get("group_uuid") or req.session.get("group_id")
    if not user_uuid or not group_id:
        return False

    # middleware request cache가 없는 legacy 호출 경로에서만 기존 세션 캐시 사용
    sess_perms = set(req.session.get("perms") or [])
    if sess_perms:
        return bool(sess_perms & needed)

    # 없으면 중앙에서 조회 후 캐시
    try:
        perms = set(C.list_permissions_for_user_in_group(user_uuid, group_id))
    except Exception:
        perms = set()
    req.session["perms"] = sorted(perms)
    return bool(perms & needed)

@register.simple_tag(takes_context=True)
def has_any_perm(context, *perm_codes: str) -> bool:
    """여러 코드 중 하나라도 있으면 True"""
    return any(has_perm(context, c) for c in perm_codes if c)

@register.simple_tag(takes_context=True)
def perms_debug(context) -> str:
    """디버그용: 현재 세션 권한을 문자열로 반환"""
    req = context.get("request")
    return ", ".join(req.session.get("perms") or [])

@register.filter
def dict_get(d, key):
    try:
        return (d or {}).get(key)
    except Exception:
        return None
