from pathlib import Path
from unittest import TestCase


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "cheonan-project-backfill.yml"


class CheonanProjectBackfillContractTests(TestCase):
    def _text(self) -> str:
        return WORKFLOW.read_text()

    def test_is_exact_release_and_production_gated(self):
        text = self._text()
        self.assertIn("environment: production", text)
        self.assertIn("release/stabilized-deploy", text)
        self.assertIn("ref: ${{ github.sha }}", text)
        self.assertIn('test "$(git rev-parse HEAD)" = "$GITHUB_SHA"', text)

    def test_is_guarded_and_idempotent(self):
        text = self._text()
        self.assertIn("EXPECTED_CONTRACTS = 753", text)
        self.assertIn("EXPECTED_BEFORE_PROJECTS = 743", text)
        self.assertIn("EXPECTED_GAP = 10", text)
        self.assertIn("pg_advisory_xact_lock", text)
        self.assertIn("FOR UPDATE", text)
        self.assertIn("if missing == 0:", text)
        self.assertIn("already_complete = True", text)
        self.assertIn("unexpected_gap", text)
        self.assertIn("postcondition_failed", text)

    def test_only_missing_projects_are_inserted(self):
        text = self._text().lower()
        self.assertIn("insert into prj.projects", text)
        self.assertIn("not exists", text)
        self.assertNotIn("insert into ctr.contracts", text)
        self.assertNotIn("update ctr.contracts", text)
        self.assertNotIn("update prj.projects", text)
        self.assertNotIn("delete from ctr.contracts", text)
        self.assertNotIn("delete from prj.projects", text)
        self.assertNotIn("truncate", text)

    def test_mapping_matches_application_contract(self):
        text = self._text()
        self.assertIn("project_code = f\"C{clean_code.replace('-', '')}\" if clean_code else None", text)
        self.assertIn('start_date, end_date, "active", json.dumps({}), now, now', text)

    def test_logs_are_aggregate_only(self):
        text = self._text()
        for forbidden in (
            "print(contract_id",
            "print(code",
            "print(name",
            "cheonan_missing_contract_",
            "cat .env",
            "printenv",
            "ps aux",
        ):
            self.assertNotIn(forbidden, text)
        self.assertIn("cheonan_project_backfill_inserted=", text)
        self.assertIn("cheonan_project_backfill_missing=0", text)

    def test_does_not_restart_or_reconfigure_services(self):
        text = self._text().lower()
        for forbidden in (
            "systemctl restart",
            "systemctl start",
            "systemctl stop",
            "systemctl reload",
            "nginx -s reload",
            "service restart",
            "aws s3",
            "git pull",
            "git reset",
        ):
            self.assertNotIn(forbidden, text)
