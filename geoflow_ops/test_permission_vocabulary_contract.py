import ast
from pathlib import Path
import re
import unittest

from control.gf_authz.vocabulary import TENANT_PERMISSION_CODES

ROOT = Path(__file__).resolve().parents[1]
PERMISSION_LITERAL = re.compile(r"^[a-z][a-z0-9_]*\.[a-z][a-z0-9_.]*$")
TEMPLATE_PERMISSION = re.compile(r"\{%\s*has_perm\s+['\"]([^'\"]+)['\"]")


def python_permission_literals(relative_path: str) -> set[str]:
    source = (ROOT / relative_path).read_text(encoding="utf-8")
    tree = ast.parse(source)
    return {
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and PERMISSION_LITERAL.fullmatch(node.value)
    }


def template_permission_literals(relative_path: str) -> set[str]:
    source = (ROOT / relative_path).read_text(encoding="utf-8")
    return set(TEMPLATE_PERMISSION.findall(source))


class PermissionVocabularyContractTests(unittest.TestCase):
    def test_active_permission_literals_match_canonical_vocabulary(self):
        used = set()
        for path in (
            "geoflow_ops/security_views.py",
            "geoflow_ops/employee_security_views.py",
            "geoflow_ops/services/entity_access.py",
        ):
            used.update(python_permission_literals(path))
        used.update(
            template_permission_literals(
                "geoflow_ops/templates/geoflow_ops/employees/employee_detail.html"
            )
        )
        self.assertEqual(used, set(TENANT_PERMISSION_CODES))


if __name__ == "__main__":
    unittest.main()
