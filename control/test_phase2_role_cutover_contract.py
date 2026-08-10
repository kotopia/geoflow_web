import hashlib
import re
from pathlib import Path

from django.test import SimpleTestCase


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "phase2-aws-role-cutover.yml"
PROBE = ROOT / "scripts" / "ops" / "phase2_role_runtime_probe.py"
GUARD = ROOT / "control" / "services" / "object_storage_runtime_preflight.py"


def _git_blob_sha(path: Path) -> str:
    content = path.read_bytes()
    payload = b"blob " + str(len(content)).encode("ascii") + b"\0" + content
    return hashlib.sha1(payload).hexdigest()


def _expected_blob(text: str, variable: str) -> str:
    match = re.search(rf"{re.escape(variable)}='([0-9a-f]{{40}})'", text)
    if not match:
        raise AssertionError(f"Missing {variable} in cutover workflow")
    return match.group(1)


class Phase2RoleCutoverContractTests(SimpleTestCase):
    def test_cutover_is_manual_and_production_gated(self):
        text = WORKFLOW.read_text()
        self.assertIn("workflow_dispatch:", text)
        self.assertNotIn("\n  push:\n", text)
        self.assertIn("environment: production", text)
        self.assertIn("ROLE_ONLY_CUTOVER", text)

    def test_cutover_checks_hidden_systemd_credential_sources(self):
        text = WORKFLOW.read_text()
        self.assertIn('systemctl show "$service" -p Environment --value', text)
        self.assertIn('systemctl cat "$service"', text)
        self.assertIn("systemd_direct_aws_credential_source_present", text)
        self.assertIn("systemd_environment_file_not_safe", text)

    def test_cutover_is_rollback_guarded_and_does_not_delete_old_keys(self):
        text = WORKFLOW.read_text()
        self.assertIn("phase2_cutover_rollback_completed=yes", text)
        self.assertIn("AWS_REQUIRE_ROLE_CREDENTIALS=1", text)
        self.assertIn("phase2_cutover_s3_put_probe=not_performed", text)
        self.assertNotIn("delete-access-key", text)
        self.assertNotIn("update-access-key", text)
        self.assertNotIn("iam delete", text.lower())

    def test_probe_checks_real_tenant_connectivity_without_identifier_logging(self):
        text = PROBE.read_text()
        self.assertIn('cursor.execute("SELECT 1")', text)
        self.assertIn("phase2_role_probe_tenant_db_connect_ok", text)
        self.assertIn("phase2_role_probe_secret_resolve_ok", text)
        self.assertIn("phase2_role_probe_s3_read", text)
        self.assertNotIn("print(config.db_", text)
        self.assertNotIn("print(bucket", text)
        self.assertNotIn("print(key", text)

    def test_probe_rejects_non_role_credential_method(self):
        text = PROBE.read_text()
        self.assertIn('{"iam-role", "container-role"}', text)
        self.assertIn("credential_source_not_role", text)

    def test_cutover_reviewed_blob_pins_match_current_guard_and_probe(self):
        text = WORKFLOW.read_text()
        self.assertEqual(
            _expected_blob(text, "expected_guard_cutover_blob"),
            _git_blob_sha(GUARD),
        )
        self.assertEqual(
            _expected_blob(text, "expected_probe_blob"),
            _git_blob_sha(PROBE),
        )
