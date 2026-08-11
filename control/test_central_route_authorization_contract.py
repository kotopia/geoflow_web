import ast
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parent


def _source(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _function_node(path: Path, function_name: str):
    tree = ast.parse(_source(path))
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == function_name:
            return node
    raise AssertionError(f"function not found: {function_name}")


def _function_source(path: Path, function_name: str) -> str:
    source = _source(path)
    node = _function_node(path, function_name)
    lines = source.splitlines()
    return "\n".join(lines[node.lineno - 1 : node.end_lineno])


def _decorator_names(path: Path, function_name: str) -> set[str]:
    node = _function_node(path, function_name)
    names = set()
    for decorator in node.decorator_list:
        target = decorator.func if isinstance(decorator, ast.Call) else decorator
        if isinstance(target, ast.Name):
            names.add(target.id)
        elif isinstance(target, ast.Attribute):
            names.add(target.attr)
    return names


def _route_handlers(path: Path) -> dict[str, str]:
    tree = ast.parse(_source(path))
    result = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
            continue
        if node.func.id != "path" or len(node.args) < 2:
            continue
        route, handler = node.args[0], node.args[1]
        if isinstance(route, ast.Constant) and isinstance(route.value, str):
            if isinstance(handler, ast.Name):
                result[route.value] = handler.id
    return result


def _catalog_admin_wrappers(path: Path) -> dict[str, str]:
    tree = ast.parse(_source(path))
    result = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
            continue
        if node.func.id != "path" or len(node.args) < 2:
            continue
        route, handler = node.args[0], node.args[1]
        if not isinstance(route, ast.Constant) or not isinstance(route.value, str):
            continue
        if not isinstance(handler, ast.Call) or not isinstance(handler.func, ast.Name):
            continue
        result[route.value] = handler.func.id
    return result


class CentralRouteAuthorizationContractTests(unittest.TestCase):
    def test_central_management_routes_stay_on_reviewed_handlers(self):
        routes = _route_handlers(ROOT / "urls.py")
        expected = {
            "mgmt/join-requests/": "join_requests_pending_view",
            "mgmt/join-requests/<uuid:req_id>/<str:action>/": "join_request_decide_view",
            "mgmt/signup-reviews/": "signup_reviews_admin",
            "mgmt/signup-reviews/<uuid:req_id>/": "signup_review_detail_admin",
            "mgmt/signup-reviews/<uuid:req_id>/<str:action>/": "signup_review_decide_admin",
            "mgmt/users/": "users_list_admin",
            "mgmt/users/<uuid:user_id>/": "users_detail_admin",
            "mgmt/users/<uuid:user_id>/assign/": "users_assign_group_admin",
            "mgmt/users/<uuid:user_id>/delete/": "users_delete_admin",
            "central/groups/": "group_list_admin",
            "central/groups/new/": "group_create_admin",
            "central/groups/<uuid:group_id>/edit/": "group_edit_admin",
            "categories/": "categories_page",
            "categories/options/": "category_options",
        }
        for route, handler in expected.items():
            with self.subTest(route=route):
                self.assertEqual(routes.get(route), handler)

    def test_central_management_handlers_require_central_admin(self):
        reviewed = {
            "views_join.py": ("join_requests_pending_view", "join_request_decide_view"),
            "views_signup_admin.py": (
                "signup_reviews_admin",
                "signup_review_detail_admin",
                "signup_review_decide_admin",
            ),
            "views_users_admin.py": (
                "users_list_admin",
                "users_detail_admin",
                "users_delete_admin",
            ),
            "views_user_assignment.py": ("users_assign_group_admin",),
            "views_groups_admin.py": (
                "group_list_admin",
                "group_create_admin",
                "group_edit_admin",
            ),
            "views_categories.py": ("categories_page", "category_options"),
        }
        for filename, functions in reviewed.items():
            for function_name in functions:
                with self.subTest(filename=filename, function=function_name):
                    decorators = _decorator_names(ROOT / filename, function_name)
                    self.assertIn("require_central_admin", decorators)

    def test_admin_mutations_retain_method_or_csrf_guards(self):
        join_decide = _decorator_names(ROOT / "views_join.py", "join_request_decide_view")
        signup_decide = _decorator_names(ROOT / "views_signup_admin.py", "signup_review_decide_admin")
        assignment = _decorator_names(ROOT / "views_user_assignment.py", "users_assign_group_admin")
        user_delete = _function_source(ROOT / "views_users_admin.py", "users_delete_admin")
        group_create = _decorator_names(ROOT / "views_groups_admin.py", "group_create_admin")
        group_edit = _decorator_names(ROOT / "views_groups_admin.py", "group_edit_admin")

        self.assertIn("require_http_methods", join_decide)
        self.assertIn("require_POST", signup_decide)
        self.assertIn("csrf_protect", assignment)
        self.assertIn('if request.method != "POST":', user_delete)
        self.assertIn("csrf_protect", group_create)
        self.assertIn("require_http_methods", group_create)
        self.assertIn("csrf_protect", group_edit)
        self.assertIn("require_http_methods", group_edit)

    def test_tenant_selection_requires_server_issued_candidate_and_post(self):
        path = ROOT / "views_groups.py"
        decorators = _decorator_names(path, "group_select_view")
        body = _function_source(path, "group_select_view")

        self.assertIn("login_required", decorators)
        self.assertIn("require_POST", decorators)
        self.assertIn("csrf_protect", decorators)
        candidate_read = 'request.session.get("tenant_candidates", [])'
        candidate_check = "if not candidate:"
        alias_write = 'request.session["tenant_db_alias"] = candidate["db_alias"]'
        self.assertIn(candidate_read, body)
        self.assertIn(candidate_check, body)
        self.assertIn(alias_write, body)
        self.assertLess(body.index(candidate_read), body.index(candidate_check))
        self.assertLess(body.index(candidate_check), body.index(alias_write))

    def test_account_password_change_remains_authenticated_and_csrf_protected(self):
        decorators = _decorator_names(
            ROOT / "views_account_security.py", "account_password_change_view"
        )
        self.assertIn("login_required", decorators)
        self.assertIn("csrf_protect", decorators)
        self.assertIn("require_http_methods", decorators)

    def test_catalog_admin_surface_remains_central_admin_wrapped(self):
        wrappers = _catalog_admin_wrappers(ROOT / "catalog" / "urls.py")
        admin_routes = [route for route in wrappers if route.startswith("admin/")]
        self.assertTrue(admin_routes)
        for route in admin_routes:
            with self.subTest(route=route):
                self.assertIn(wrappers[route], {"_admin", "_admin_post"})

        catalog_urls = _source(ROOT / "catalog" / "urls.py")
        self.assertIn(
            "path('facet-options/', login_required(views.facet_options), name='facet_options')",
            catalog_urls,
        )


if __name__ == "__main__":
    unittest.main()
