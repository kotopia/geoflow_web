from __future__ import annotations

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_POST

from control.gf_authz.permissions import gf_get_roles, gf_has_perm
from geoflow_ops.services.entity_access import require_tenant_context

from . import views


MANAGER_ROLES = {"tenant_admin", "tenant_administrator", "manager", "tenant_manager", "super_admin"}


def _require_view(request) -> str:
    alias = require_tenant_context(request)
    if not gf_has_perm(request, "contracts.view"):
        raise PermissionDenied("Permission denied")
    return alias


def _can_review(request) -> bool:
    return gf_has_perm(request, "contracts.create") or gf_has_perm(request, "contracts.edit")


def _can_manage(request) -> bool:
    return _can_review(request) and bool(gf_get_roles(request) & MANAGER_ROLES)


def _require_review(request) -> str:
    alias = _require_view(request)
    if not _can_review(request):
        raise PermissionDenied("Permission denied")
    return alias


def _require_manage(request) -> str:
    alias = _require_review(request)
    if not _can_manage(request):
        raise PermissionDenied("Manager permission required")
    return alias


@never_cache
@login_required
@require_GET
def notice_list(request):
    alias = _require_view(request)
    return views.notice_list(request, alias, can_review=_can_review(request), can_manage=_can_manage(request))


@never_cache
@login_required
@require_GET
def settings_page(request):
    return views.settings_page(request, _require_manage(request))


@never_cache
@login_required
@require_POST
def filter_value_save(request):
    return views.filter_value_save(request, _require_manage(request))


@never_cache
@login_required
@require_POST
def keyword_save(request):
    return views.keyword_save(request, _require_manage(request))


@never_cache
@login_required
@require_POST
def review_save(request, notice_id):
    return views.review_save(request, _require_review(request), notice_id)


@never_cache
@login_required
@require_POST
def sync_now(request):
    return views.sync_now(request, _require_manage(request))
