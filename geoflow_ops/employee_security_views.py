from __future__ import annotations

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_http_methods

from control.gf_authz.permissions import gf_has_perm

from . import views_employee_profile, views_employee_role_request
from .services.employee_access import employee_access_policy
from .services.entity_access import require_tenant_context


def _require(request, permission: str) -> None:
    """Compatibility permission wrapper retained for shared route-contract tests."""
    require_tenant_context(request)
    if not gf_has_perm(request, permission):
        raise PermissionDenied("Permission denied")


def _policy(request):
    alias = require_tenant_context(request)
    return alias, employee_access_policy(request, alias)


@never_cache
@login_required
@require_GET
def employee_list(request):
    _, policy = _policy(request)
    if not policy.can_list:
        return views_employee_profile.employee_me(request)
    return views_employee_profile.employees_list(request)


@never_cache
@login_required
@require_GET
def employee_me(request):
    _policy(request)
    return views_employee_profile.employee_me(request)


@never_cache
@login_required
@require_http_methods(["GET", "POST"])
def employee_create(request):
    _, policy = _policy(request)
    if not policy.can_create:
        raise PermissionDenied("Permission denied")
    return views_employee_profile.employees_create(request)


@never_cache
@login_required
@require_http_methods(["GET", "POST"])
def employee_detail(request, emp_id):
    _, policy = _policy(request)
    if not policy.can_view(emp_id):
        raise PermissionDenied("Permission denied")
    if request.method == "POST":
        if not policy.can_edit(emp_id):
            raise PermissionDenied("Permission denied")
        # Keep the established directory.edit boundary for manager-controlled
        # organization/grade/employment fields. Self-service writes are still
        # allowed by policy, but those fields are not accepted by the profile view.
        if policy.can_edit_admin_fields(emp_id) and not gf_has_perm(request, "directory.edit"):
            raise PermissionDenied("Permission denied")
    return views_employee_profile.employees_detail(request, emp_id)


@login_required
@require_GET
def hr_options(request, category):
    _, policy = _policy(request)
    if not policy.self_employee_id and not policy.can_list:
        raise PermissionDenied("Permission denied")
    return views_employee_profile.hr_options(request, category)


@never_cache
@login_required
@require_http_methods(["GET", "POST"])
def employee_role_request(request, emp_id):
    _, policy = _policy(request)
    if (
        not policy.can_assign_roles
        or not policy.can_edit_admin_fields(emp_id)
        or not gf_has_perm(request, "directory.roles.assign")
    ):
        raise PermissionDenied("Permission denied")
    return views_employee_role_request.employees_request_role_safe(request, emp_id)
