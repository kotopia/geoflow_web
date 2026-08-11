import ast
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parent


def _function_source(path: Path, function_name: str) -> str:
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == function_name:
            lines = source.splitlines()
            return "\n".join(lines[node.lineno - 1 : node.end_lineno])
    raise AssertionError(f"function not found: {function_name}")


class CatalogBoardAuthorizationStaticTests(unittest.TestCase):
    def test_catalog_board_requires_projects_view_before_optional_project_scope(self):
        body = _function_source(ROOT / "security_views.py", "catalog_board")
        permission_guard = '_require(request, "projects.view")'
        project_lookup = 'project_id = request.GET.get("project_id")'

        self.assertIn(permission_guard, body)
        self.assertIn(project_lookup, body)
        self.assertLess(body.index(permission_guard), body.index(project_lookup))
        self.assertNotIn('if not gf_has_perm(request, "projects.view")', body)

    def test_catalog_board_still_fail_closes_invalid_project_ids_and_delegates(self):
        body = _function_source(ROOT / "security_views.py", "catalog_board")

        self.assertIn("UUID(str(project_id))", body)
        self.assertIn('raise PermissionDenied("Permission denied")', body)
        self.assertIn("return views_catalog.catalog_board(request)", body)


if __name__ == "__main__":
    unittest.main()
