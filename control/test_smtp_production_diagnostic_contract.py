from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "phase1-smtp-production-diagnostic.yml"


class SmtpProductionDiagnosticContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = WORKFLOW.read_text(encoding="utf-8")

    def test_server_diagnostic_runs_after_desired_secret_auth_failure(self):
        desired = self.source.index("- name: Validate desired SMTP secrets without mutation")
        continuation = self.source.index("continue-on-error: true", desired)
        server = self.source.index("- name: Diagnose current server SMTP without mutation")
        self.assertLess(desired, continuation)
        self.assertLess(continuation, server)

    def test_both_diagnostics_remain_non_mutating(self):
        self.assertIn("github_smtp_diagnostic_result", self.source)
        self.assertIn("server_smtp_diagnostic_result", self.source)
        lowered = self.source.lower()
        for forbidden in (
            "systemctl restart",
            "systemctl reload",
            "manage.py migrate",
            "git checkout",
            "sed -i",
        ):
            self.assertNotIn(forbidden, lowered)


if __name__ == "__main__":
    unittest.main()
