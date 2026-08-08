from __future__ import annotations

from dataclasses import dataclass

from django.urls import Resolver404, resolve


_UUID = "00000000-0000-0000-0000-000000000001"
ROUTE_SECURITY_BOUNDARIES = (
    ("/control/logout/", "control:logout", "control.views_session", "logout_view"),
    ("/", "tenant:home", "geoflow_ops.views_home_security", "tenant_home"),
    ("/projects/", "tenant:project_list", "geoflow_ops.security_views", "project_list"),
    ("/catalog/board/", "tenant:catalog_board", "geoflow_ops.security_views", "catalog_board"),
    (f"/contracts/{_UUID}/json/", "tenant:contract_json", "geoflow_ops.security_views", "contract_json"),
    (f"/partners/{_UUID}/json/", "tenant:partner_detail_json", "geoflow_ops.security_views", "partner_json"),
    ("/api/uploads/presign-put/", "tenant:upload_presign_put", "geoflow_ops.upload_guard_views", "presign_put"),
    ("/api/uploads/commit/", "tenant:upload_commit", "geoflow_ops.upload_guard_views", "commit"),
    (f"/api/uploads/presign-get/{_UUID}/", "tenant:upload_presign_get", "geoflow_ops.upload_guard_views", "presign_get"),
    ("/api/events/create/", "tenant:event_create", "geoflow_ops.views_events", "create_event"),
    ("/events/ui/modal/", "tenant:event_modal_ui", "geoflow_ops.security_views", "event_modal_ui"),
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
