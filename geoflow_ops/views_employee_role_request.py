from django.contrib import messages
from django.contrib.auth.decorators import login_required
import logging

from django.db import DatabaseError, connections
from django.http import HttpResponseForbidden
from django.shortcuts import redirect, render

from control.decorators import require_perm
from control.middleware import current_db_alias
from control.services import central_repo as C
from control.services.tenant_role_request_service import (
    TenantRoleRequest,
    TenantRoleRequestRejected,
    queue_tenant_role_request,
)
from control.services_identity import lookup_user_id_from_request

from .views_employees import _is_forbidden_central_role, _require_role_code_column


logger = logging.getLogger(__name__)


@login_required
@require_perm("directory.roles.assign")
def employees_request_role_safe(request, emp_id):
    """Request a tenant role without provisioning or mutating central identities."""

    alias = current_db_alias()
    _require_role_code_column(alias)

    with connections[alias].cursor() as cursor:
        cursor.execute(
            "SELECT email, name, role_code FROM hr.employee_profile WHERE id=%s LIMIT 1",
            [str(emp_id)],
        )
        row = cursor.fetchone()
    if not row:
        messages.error(request, "직원을 찾을 수 없습니다.")
        return redirect("tenant:employees_list")

    target_email = (row[0] or "").strip().lower()
    target_name = row[1] or ""
    current_role_code = (row[2] or "").strip()
    if not target_email:
        messages.error(request, "대상 직원의 이메일이 필요합니다.")
        return redirect("tenant:employees_detail", emp_id=emp_id)

    if request.method == "GET":
        roles = C.list_active_roles()
        role_codes = [
            role["code"]
            for role in roles
            if not _is_forbidden_central_role(role["code"])
        ]
        return render(
            request,
            "geoflow_ops/employees/employee_request_role.html",
            {
                "emp_id": emp_id,
                "employee_email": target_email,
                "employee_name": target_name,
                "current_role_code": current_role_code,
                "role_codes": role_codes,
            },
        )

    requester_user_id = lookup_user_id_from_request(request)
    group_id = request.session.get("group_uuid") or request.session.get("group_id")
    role_code = (request.POST.get("role_code") or "").strip()
    if not requester_user_id or not group_id or not role_code:
        messages.error(request, "권한 요청을 처리할 수 없습니다. 계정·그룹·역할 상태를 확인하세요.")
        return HttpResponseForbidden("Forbidden")
    if _is_forbidden_central_role(role_code):
        messages.error(request, "해당 역할은 테넌트에서 요청할 수 없습니다.")
        return redirect("tenant:employees_detail", emp_id=emp_id)

    try:
        queue_tenant_role_request(
            TenantRoleRequest(
                requester_user_id=str(requester_user_id),
                group_id=str(group_id),
                requested_email=target_email,
                role_code=role_code,
            )
        )
    except (TenantRoleRequestRejected, ValueError):
        messages.error(request, "권한 요청을 처리할 수 없습니다. 중앙 계정 상태를 확인하세요.")
        return HttpResponseForbidden("Forbidden")
    except DatabaseError:
        logger.warning("Tenant role request transaction failed")
        messages.error(request, "권한 요청을 처리할 수 없습니다. 잠시 후 다시 시도해 주세요.")
        return HttpResponseForbidden("Forbidden")

    messages.success(request, "권한 요청이 접수되었습니다.")
    return redirect("tenant:employees_detail", emp_id=emp_id)
