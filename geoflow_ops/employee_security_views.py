from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.views.decorators.http import require_GET, require_http_methods

from control.gf_authz.permissions import gf_has_perm

from . import views_employee_role_request, views_employees
from .services.entity_access import require_tenant_context


def _require(request, permission: str) -> None:
    require_tenant_context(request)
    if not gf_has_perm(request, permission):
        raise PermissionDenied("Permission denied")


@login_required
@require_GET
def employee_list(request):
    _require(request, "directory.view")
    return views_employees.employees_list(request)


@login_required
@require_http_methods(["GET", "POST"])
def employee_create(request):
    _require(request, "directory.edit")
    return views_employees.employees_create(request)


@login_required
@require_http_methods(["GET", "POST"])
def employee_detail(request, emp_id):
    _require(request, "directory.view")
    if request.method == "POST" and not gf_has_perm(request, "directory.edit"):
        raise PermissionDenied("Permission denied")
    return views_employees.employees_detail(request, emp_id)


@login_required
@require_GET
def hr_options(request, category):
    _require(request, "directory.view")
    return views_employees.hr_options(request, category)


@login_required
@require_http_methods(["GET", "POST"])
def employee_role_request(request, emp_id):
    _require(request, "directory.roles.assign")
    return views_employee_role_request.employees_request_role_safe(request, emp_id)
