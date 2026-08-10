from pathlib import Path
from unittest import TestCase


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "cheonan-contract-project-consistency-diagnostic.yml"


class CheonanContractProjectConsistencyDiagnosticContractTests(TestCase):
    def _text(self) -> str:
        return WORKFLOW.read_text()

    def test_is_release_push_only_and_production_gated(self):
        text = self._text()
        self.assertIn("push:", text)
        self.assertIn("release/stabilized-deploy", text)
        self.assertIn("cheonan-contract-project-consistency-diagnostic.yml", text)
        self.assertNotIn("workflow_dispatch:", text)
        self.assertNotIn("pull_request:", text)
        self.assertIn("environment: production", text)
        self.assertIn('test "$(git rev-parse HEAD)" = "$GITHUB_SHA"', text)

    def test_targets_only_cheonan_and_forces_read_only_transaction(self):
        text = self._text()
        self.assertIn('ALIAS = "cheonan_db"', text)
        self.assertIn("SET LOCAL TRANSACTION READ ONLY", text)
        self.assertIn("ctr.contracts", text)
        self.assertIn("prj.projects", text)

    def test_reports_relationship_and_history_signals(self):
        text = self._text()
        for marker in (
            "cheonan_contracts_total=",
            "cheonan_projects_total=",
            "cheonan_distinct_contracts_with_project=",
            "cheonan_contracts_without_project=",
            "cheonan_contracts_with_multiple_projects=",
            "cheonan_orphan_project_links=",
            "cheonan_missing_with_legacy_id=",
            "cheonan_missing_since_repo_init=",
            "cheonan_missing_among_newest_20=",
            "cheonan_contract_user_trigger_count=",
            "cheonan_project_contract_unique_constraints=",
            "cheonan_contract_project_diagnostic_complete=yes",
        ):
            self.assertIn(marker, text)

    def test_has_no_database_or_service_mutation(self):
        text = self._text().lower()
        forbidden = (
            " insert ",
            " update ",
            " delete ",
            " truncate ",
            " alter table",
            " create table",
            " drop table",
            "systemctl restart",
            "systemctl start",
            "systemctl stop",
            "nginx -s reload",
            "systemctl reload",
            "aws s3",
            "migrate --database",
        )
        padded = f" {text} "
        for token in forbidden:
            self.assertNotIn(token, padded)

    def test_does_not_print_database_credentials_or_environment(self):
        text = self._text().lower()
        for forbidden in (
            "printenv",
            "cat .env",
            "-p environment",
            "-p environmentfiles",
            "settings.databases[alias]['password']",
            'settings.databases[alias]["password"]',
        ):
            self.assertNotIn(forbidden, text)
