from __future__ import annotations

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_POST

from . import views_settings
from .services.employee_access import employee_access_policy
from .services.entity_access import require_tenant_context


def _require_settings_manager(request):
    alias = require_tenant_context(request)
    policy = employee_access_policy(request, alias)
    if not policy.can_manage_settings:
        raise PermissionDenied("Permission denied")
    return alias


@never_cache
@login_required
@require_GET
def settings_page(request):
    _require_settings_manager(request)
    return views_settings.settings_page(request)


@never_cache
@login_required
@require_POST
def settings_node_save(request):
    _require_settings_manager(request)
    return views_settings.settings_node_save(request)


@never_cache
@login_required
@require_POST
def department_save(request):
    _require_settings_manager(request)
    return views_settings.department_save(request)
