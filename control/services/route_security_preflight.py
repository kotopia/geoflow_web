from __future__ import annotations

from dataclasses import dataclass

from django.urls import Resolver404, resolve


_UUID = "00000000-0000-0000-0000-000000000001"
ROUTE_SECURITY_BOUNDARIES = (
    ("/login/", "login", "control.views_login_security", "login_view"),
    ("/control/logout/", "control:logout", "control.views_session", "logout_view"),
    ("/", "tenant:home", "geoflow_ops.views_home_security", "tenant_home"),
    ("/contracts/", "tenant:contract_list", "geoflow_ops.security_views", "contract_list"),
    ("/contracts/new/", "tenant:contract_create", "geoflow_ops.security_views", "contract_create"),
    (f"/contracts/{_UUID}/", "tenant:contract_detail", "geoflow_ops.security_views", "contract_detail"),
    (f"/contracts/{_UUID}/json/", "tenant:contract_json", "geoflow_ops.security_views", "contract_json"),
    ("/partners/", "tenant:partner_list", "geoflow_ops.security_views", "partner_list"),
    ("/partners/new/", "tenant:partner_create", "geoflow_ops.security_views", "partner_create"),
    (f"/partners/{_UUID}/", "tenant:partner_detail", "geoflow_ops.security_views", "partner_detail"),
    (f"/partners/{_UUID}/json/", "tenant:partner_detail_json", "geoflow_ops.security_views", "partner_json"),
    ("/partners/options/", "tenant:partner_options", "geoflow_ops.security_views", "partner_options"),
    ("/projects/", "tenant:project_list", "geoflow_ops.security_views", "project_list"),
    (f"/projects/{_UUID}/json/", "tenant:project_detail_json", "geoflow_ops.security_views", "project_json"),
    (f"/projects/{_UUID}/summary/", "tenant:project_summary", "geoflow_ops.security_views", "project_summary"),
    (f"/projects/{_UUID}/summary-save/", "tenant:project_summary_save", "geoflow_ops.security_views", "project_summary_save"),
    ("/catalog/board/", "tenant:catalog_board", "geoflow_ops.security_views", "catalog_board"),
    (f"/projects/{_UUID}/scope-modal/", "tenant:project_scope_modal", "geoflow_ops.security_views", "project_scope_modal"),
    (f"/projects/{_UUID}/scope-data/", "tenant:project_scope_data", "geoflow_ops.security_views", "project_scope_data"),
    (f"/projects/{_UUID}/scope-save/", "tenant:project_scope_save", "geoflow_ops.security_views", "project_scope_save"),
    (f"/projects/{_UUID}/scope-summary/", "tenant:project_scope_summary", "geoflow_ops.security_views", "project_scope_summary"),
    ("/employees/", "tenant:employees_list", "geoflow_ops.employee_security_views", "employee_list"),
    ("/employees/new/", "tenant:employees_create", "geoflow_ops.employee_security_views", "employee_create"),
    (f"/employees/{_UUID}/", "tenant:employees_detail", "geoflow_ops.employee_security_views", "employee_detail"),
    (f"/employees/{_UUID}/request-role/", "tenant:employees_request_role", "geoflow_ops.employee_security_views", "employee_role_request"),
    ("/api/hr/options/status/", "tenant:hr_options", "geoflow_ops.employee_security_views", "hr_options"),
    ("/api/uploads/presign-put/", "tenant:upload_presign_put", "geoflow_ops.upload_guard_views", "presign_put"),
    ("/api/uploads/commit/", "tenant:upload_commit", "geoflow_ops.upload_guard_views", "commit"),
    (f"/api/uploads/presign-get/{_UUID}/", "tenant:upload_presign_get", "geoflow_ops.upload_guard_views", "presign_get"),
    ("/api/events/create/", "tenant:event_create", "geoflow_ops.views_events", "create_event"),
    ("/events/ui/modal/", "tenant:event_modal_ui", "geoflow_ops.security_views", "event_modal_ui"),
    (f"/control/set-password/{_UUID}/", "control:set_password", "control.views_legacy_password_security", "legacy_password_setup_view"),
    ("/control/account/set-password/legacy-token/", "control:account_set_password", "control.views_legacy_password_security", "legacy_password_setup_view"),
)


@dataclass(frozen=True)
class RouteSecurityBoundaryCheck:
    code: str
    ready: bool
    message: str


def inspect_route_security_boundaries() -> tuple[RouteSecurityBoundaryCheck, ...]:
    """Verify security-sensitive URL routes still point at reviewed boundary views."""

    checks: list[RouteSecurityBoundaryCheck] = []
    for path, expected_view_name, expected_module, expected_name in ROUTE_SECURITY_BOUNDARIES:
        code = "route_boundary_" + expected_view_name.replace(":", "_")
        try:
            match = resolve(path)
        except Resolver404:
            checks.append(
                RouteSecurityBoundaryCheck(
                    code=code,
                    ready=False,
                    message="Required security-sensitive route is not resolvable.",
                )
            )
            continue

        func = match.func
        module = str(getattr(func, "__module__", ""))
        name = str(getattr(func, "__name__", ""))
        ready = bool(
            match.view_name == expected_view_name
            and module == expected_module
            and name == expected_name
        )
        checks.append(
            RouteSecurityBoundaryCheck(
                code=code,
                ready=ready,
                message=(
                    "Reviewed route boundary is intact."
                    if ready
                    else "Security-sensitive route no longer points at the reviewed boundary view."
                ),
            )
        )
    return tuple(checks)
