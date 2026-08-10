from pathlib import Path
from unittest import TestCase


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "cheonan-contract-project-integrity-diagnostic.yml"


class CheonanContractProjectIntegrityContractTests(TestCase):
    def _text(self) -> str:
        return WORKFLOW.read_text()

    def test_is_production_gated_and_exact_release(self):
        text = self._text()
        self.assertIn("environment: production", text)
        self.assertIn("release/stabilized-deploy", text)
        self.assertIn('test "$(git rev-parse HEAD)" = "$GITHUB_SHA"', text)

    def test_targets_only_cheonan_and_uses_read_only_transaction(self):
        text = self._text()
        self.assertIn('alias = "cheonan_db"', text)
        self.assertIn("SET TRANSACTION READ ONLY", text)
        self.assertIn("ctr.contracts", text)
        self.assertIn("prj.projects", text)

    def test_reports_only_bounded_integrity_metadata(self):
        text = self._text()
        for key in (
            "cheonan_cp_contract_total=",
            "cheonan_cp_project_total=",
            "cheonan_cp_distinct_linked_contracts=",
            "cheonan_cp_missing_contracts=",
            "cheonan_cp_projects_without_contract=",
            "cheonan_cp_contracts_with_multiple_projects=",
            "cheonan_cp_missing_legacy_id_present=",
            "cheonan_cp_missing_created_before_repo_init=",
            "cheonan_cp_missing_created_on_or_after_repo_init=",
            "cheonan_cp_missing_among_latest_20_contracts=",
            "cheonan_cp_contract_insert_trigger_present=",
            "cheonan_cp_project_contract_fk_present=",
            "cheonan_cp_project_contract_unique_present=",
        ):
            self.assertIn(key, text)
        self.assertNotIn("c.name", text)
        self.assertNotIn("c.code", text)
        self.assertNotIn("c.id::text", text)

    def test_has_no_database_or_service_mutation(self):
        text = self._text().lower()
        for forbidden in (
            " insert ",
            " update ",
            " delete ",
            " truncate ",
            " alter table",
            " drop table",
            " create table",
            "systemctl restart",
            "systemctl start",
            "systemctl stop",
            "systemctl reload",
            "git pull",
            "git reset",
            "aws s3",
            "printenv",
            "cat .env",
        ):
            self.assertNotIn(forbidden, text)
