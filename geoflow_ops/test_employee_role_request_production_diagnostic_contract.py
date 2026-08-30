from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "employee-role-request-production-diagnostic.yml"


class EmployeeRoleRequestProductionDiagnosticContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = WORKFLOW.read_text(encoding="utf-8")
        cls.lowered = cls.source.lower()

    def test_is_manual_read_only_production_diagnostic(self):
        self.assertIn("push:", self.source)
        self.assertIn("release/stabilized-deploy", self.source)
        self.assertIn(".github/workflows/employee-role-request-production-diagnostic.yml", self.source)
        self.assertIn("workflow_dispatch:", self.source)
        self.assertIn("environment: production", self.source)
        self.assertIn("permissions:\n  contents: read", self.source)
        self.assertIn("journalctl", self.source)
        self.assertIn("--since '3 hours ago'", self.source)

    def test_only_sanitized_failure_classification_is_emitted(self):
        self.assertIn("role_request_diagnostic_matching_500s", self.source)
        self.assertIn("role_request_diagnostic_exception", self.source)
        self.assertIn("role_request_diagnostic_message", self.source)
        self.assertIn("for line in block.splitlines()", self.source)
        self.assertIn("match.group(1), match.group(2)", self.source)
        self.assertIn('"<uuid>"', self.source)
        self.assertNotIn("print(block)", self.source)
        self.assertNotIn("print(text)", self.source)

    def test_diagnostic_contains_no_mutating_or_restart_commands(self):
        for forbidden in (
            " delete from ", " update ", " insert into ", " alter table ",
            " drop table ", " truncate ", "systemctl restart", "git checkout",
            "manage.py migrate", "collectstatic",
        ):
            self.assertNotIn(forbidden, self.lowered)


if __name__ == "__main__":
    unittest.main()
