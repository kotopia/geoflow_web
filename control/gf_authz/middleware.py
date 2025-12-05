from django.utils.deprecation import MiddlewareMixin
from .services import gf_load_user_context

class GFAuthzContextMiddleware(MiddlewareMixin):
    """
    - 세션/DB에서 roles, perms, tenant_id, project_ids를 로딩해 request에 주입
    - 기존 게이트(중앙/테넌트 구분)는 건드리지 않음
    """
    WHITELIST_PREFIXES = ("/static/", "/health")

    def process_request(self, request):
        path = request.path
        if path.startswith(self.WHITELIST_PREFIXES):
            return None

        if request.user.is_authenticated:
            ctx = request.session.get("gf_authz_ctx")
            if not ctx:
                ctx = gf_load_user_context(request)
                request.session["gf_authz_ctx"] = ctx
                request.session["gf_perms"] = ctx.get("perms", [])
                request.session["gf_roles"] = ctx.get("roles", [])

            # request 주입 (캐시)
            request.gf_tenant_id = ctx.get("tenant_id")
            request.gf_project_ids = set(ctx.get("project_ids") or [])
            request._gf_perms_cache = set(ctx.get("perms") or [])
            request._gf_roles_cache = set(ctx.get("roles") or [])
        return None
