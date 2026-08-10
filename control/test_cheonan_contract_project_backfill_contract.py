from pathlib import Path
from unittest import TestCase


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "cheonan-contract-project-backfill.yml"


class CheonanContractProjectBackfillContractTests(TestCase):
    def _text(self) -> str:
        return WORKFLOW.read_text()

    def test_is_production_gated_and_exact_release(self):
        text = self._text()
        self.assertIn("environment: production", text)
        self.assertIn("release/stabilized-deploy", text)
        self.assertIn('ref: ${{ github.sha }}', text)
        self.assertIn("runtime_release_sha_mismatch", text)

    def test_is_guarded_to_known_shape(self):
        text = self._text()
        self.assertIn("EXPECTED_CONTRACTS = 753", text)
        self.assertIn("EXPECTED_PROJECTS_BEFORE = 743", text)
        self.assertIn("EXPECTED_MISSING = 10", text)
        self.assertIn("select_for_update()", text)
        self.assertIn("with transaction.atomic(using=ALIAS):", text)
        self.assertIn("create_project_for_contract(ALIAS, contract", text)
        self.assertIn("post-insert verification failed; transaction will roll back", text)

    def test_logs_aggregates_not_business_rows(self):
        text = self._text()
        for forbidden in (
            "contract.name",
            "contract.code",
            "print(contract",
            "values_list(\"code\"",
            "values_list('code'",
            "values_list(\"name\"",
            "values_list('name'",
        ):
            self.assertNotIn(forbidden, text)
        self.assertIn("before_missing=", text)
        self.assertIn("after_missing=", text)

    def test_does_not_touch_unrelated_production_state(self):
        text = self._text().lower()
        for forbidden in (
            "systemctl restart",
            "systemctl stop",
            "systemctl start",
            "nginx -s reload",
            "git pull",
            "git reset",
            "aws s3",
            "printenv",
            "cat .env",
            "delete()",
            "contract.save(",
        ):
            self.assertNotIn(forbidden, text)
