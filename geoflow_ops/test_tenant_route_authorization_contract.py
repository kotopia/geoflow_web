import ast
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parent


def _source(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _function_source(path: Path, function_name: str) -> str:
    source = _source(path)
    tree = ast.parse(source)
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == function_name:
            lines = source.splitlines()
            return "\n".join(lines[node.lineno - 1 : node.end_lineno])
    raise AssertionError(f"function not found: {function_name}")


def _route_handlers(path: Path) -> dict[str, str]:
    tree = ast.parse(_source(path))
    result = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not node.args:
            continue
        if not isinstance(node.func, ast.Name) or node.func.id != "path":
            continue
        route = node.args[0]
        handler = node.args[1] if len(node.args) > 1 else None
        if not isinstance(route, ast.Constant) or not isinstance(route.value, str):
            continue
        if isinstance(handler, ast.Attribute) and isinstance(handler.value, ast.Name):
            result[route.value] = f"{handler.value.id}.{handler.attr}"
        elif isinstance(handler, ast.Name):
            result[route.value] = handler.id
    return result


class TenantRouteAuthorizationContractTests(unittest.TestCase):
    def test_sensitive_tenant_routes_stay_on_guarded_handlers(self):
        routes = _route_handlers(ROOT / "urls.py")
        expected = {
            "": "tenant_home",
            "contracts/": "security_views.contract_list",
            "contracts/new/": "security_views.contract_create",
            "contracts/<uuid:pk>/": "security_views.contract_detail",
            "contracts/<uuid:pk>/json/": "security_views.contract_json",
            "partners/": "security_views.partner_list",
            "partners/new/": "security_views.partner_create",
            "partners/<uuid:pk>/": "security_views.partner_detail",
            "partners/<uuid:pk>/json/": "security_views.partner_json",
            "partners/options/": "security_views.partner_options",
            "catalog/board/": "security_views.catalog_board",
            "projects/": "security_views.project_list",
            "projects/<uuid:pk>/": "security_views.project_detail",
            "projects/<uuid:pk>/json/": "security_views.project_json",
            "projects/<uuid:pk>/summary/": "security_views.project_summary",
            "projects/<uuid:pk>/summary-save/": "security_views.project_summary_save",
            "projects/<uuid:pk>/scope-modal/": "security_views.project_scope_modal",
            "projects/<uuid:pk>/scope-save/": "security_views.project_scope_save",
            "projects/<uuid:pk>/scope-summary/": "security_views.project_scope_summary",
            "projects/<uuid:pk>/scope-data/": "security_views.project_scope_data",
            "employees/": "employee_security_views.employee_list",
            "employees/new/": "employee_security_views.employee_create",
            "employees/<uuid:emp_id>/": "employee_security_views.employee_detail",
            "employees/<uuid:emp_id>/request-role/": "employee_security_views.employee_role_request",
            "api/hr/options/<str:category>/": "employee_security_views.hr_options",
            "myinfo/org-units/": "security_views.orgunit_list",
            "myinfo/org-units/new/": "security_views.orgunit_create",
            "myinfo/org-units/<uuid:pk>/": "security_views.orgunit_detail",
            "myinfo/org-units/<uuid:pk>/edit/": "security_views.orgunit_update",
            "api/uploads/presign-put/": "upload_guard_views.presign_put",
            "api/uploads/commit/": "upload_guard_views.commit",
            "api/uploads/presign-get/<uuid:attachment_id>/": "upload_guard_views.presign_get",
            "api/uploads/delete/<uuid:attachment_id>/": "views_uploads.delete_attachment",
            "api/events/create/": "event_security_views.event_create",
            "api/events/list/": "event_security_views.event_list",
            "api/events/update/<uuid:event_id>/": "event_security_views.event_update",
            "api/events/assignment-options/": "views_workboard.assignment_options",
            "api/events/delete/<uuid:event_id>/": "views_events.delete_event",
            "events/ui/modal/": "security_views.event_modal_ui",
        }
        for route, handler in expected.items():
            with self.subTest(route=route):
                self.assertEqual(routes.get(route), handler)

    def test_shared_permission_wrappers_require_tenant_before_permission(self):
        for filename in ("security_views.py", "employee_security_views.py"):
            with self.subTest(filename=filename):
                body = _function_source(ROOT / filename, "_require")
                tenant_guard = "require_tenant_context(request)"
                permission_guard = "gf_has_perm(request,"
                self.assertIn(tenant_guard, body)
                self.assertIn(permission_guard, body)
                self.assertLess(body.index(tenant_guard), body.index(permission_guard))

    def test_direct_event_routes_authorize_scope_server_side(self):
        path = ROOT / "views_events.py"
        create = _function_source(path, "create_event")
        listing = _function_source(path, "list_events")
        update = _function_source(path, "update_event")
        delete = _function_source(path, "delete_event")

        self.assertLess(
            create.index("require_tenant_context(request)"),
            create.index("authorize_scope_write(request, alias, scope_type, scope_id)"),
        )
        self.assertLess(
            listing.index("require_tenant_context(request)"),
            listing.index("authorize_scope_read(request, alias, scope_type, scope_id)"),
        )
        for body in (update, delete):
            with self.subTest(handler="update" if body is update else "delete"):
                tenant_guard = "require_tenant_context(request)"
                event_guard = "get_event_for_access(request, alias, event_id, write=True)"
                self.assertIn(tenant_guard, body)
                self.assertIn(event_guard, body)
                self.assertLess(body.index(tenant_guard), body.index(event_guard))

    def test_event_security_wrappers_add_assignment_guard_without_bypassing_canonical_scope_guard(self):
        path = ROOT / "event_security_views.py"
        create = _function_source(path, "event_create")
        update = _function_source(path, "event_update")

        for body, delegated in (
            (create, "return views_events.create_event(request)"),
            (update, "return views_events.update_event(request, event_id)"),
        ):
            self.assertIn("require_tenant_context(request)", body)
            self.assertIn("_assignment_write_forbidden(request)", body)
            self.assertIn(delegated, body)
            self.assertLess(
                body.index("require_tenant_context(request)"),
                body.index("_assignment_write_forbidden(request)"),
            )
            self.assertLess(
                body.index("_assignment_write_forbidden(request)"),
                body.index(delegated),
            )

    def test_assignment_options_require_tenant_scope_write_and_directory_read(self):
        body = _function_source(ROOT / "views_workboard.py", "assignment_options")
        for guard in (
            "require_tenant_context(request)",
            "authorize_scope_read(request, alias, scope_type, scope_id)",
            "has_scope_permission(request, scope_type, write=True)",
            'gf_has_perm(request, "directory.view")',
        ):
            self.assertIn(guard, body)

    def test_upload_routes_retain_entity_authorization(self):
        uploads = ROOT / "views_uploads.py"
        guard = ROOT / "upload_guard_views.py"

        for function_name in ("presign_put", "commit"):
            with self.subTest(function=function_name):
                body = _function_source(uploads, function_name)
                tenant_guard = "require_tenant_context(request)"
                entity_guard = "authorize_attachment_write(request, alias, entity_type, entity_id)"
                self.assertIn(tenant_guard, body)
                self.assertIn(entity_guard, body)
                self.assertLess(body.index(tenant_guard), body.index(entity_guard))

        delete = _function_source(uploads, "delete_attachment")
        self.assertLess(
            delete.index("require_tenant_context(request)"),
            delete.index("authorize_attachment_write(request, alias, att.entity_type, att.entity_id)"),
        )

        get_body = _function_source(guard, "presign_get")
        self.assertLess(
            get_body.index("require_tenant_context(request)"),
            get_body.index("authorize_attachment_read(request, alias, attachment)"),
        )

        for function_name in ("presign_put", "commit"):
            delegated = _function_source(guard, function_name)
            self.assertIn(f"return views_uploads.{function_name}(request)", delegated)

    def test_scope_permission_contract_is_fail_closed_and_explicit(self):
        source = _source(ROOT / "services" / "entity_access.py")
        for expected in (
            '"contract": {"read": "contracts.view", "write": "contracts.edit"}',
            '"project": {"read": "projects.view", "write": "projects.edit"}',
            '"employee": {"read": "directory.view", "write": "directory.edit"}',
            '"orgunit": {"read": "directory.view", "write": "directory.edit"}',
        ):
            self.assertIn(expected, source)
        self.assertIn("if not alias or alias == central_alias or not session_alias or session_alias != alias:", source)
        self.assertIn('raise PermissionDenied("Tenant access denied.")', source)


if __name__ == "__main__":
    unittest.main()
