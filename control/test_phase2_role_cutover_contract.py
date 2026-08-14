import hashlib
import json
import re
from pathlib import Path

from django.test import SimpleTestCase


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "phase2-aws-role-cutover.yml"
READINESS_WORKFLOW = ROOT / ".github" / "workflows" / "phase2-aws-role-readiness-diagnostic.yml"
READINESS_PROBE = ROOT / "scripts" / "ops" / "phase2_aws_role_readiness_probe.py"
PROBE = ROOT / "scripts" / "ops" / "phase2_role_runtime_probe.py"
GUARD = ROOT / "control" / "services" / "object_storage_runtime_preflight.py"
RULESET_TEMPLATE = ROOT / "docs" / "phase2-release-ruleset-api-template.json"


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
        self.assertIn("AWS_EC2_METADATA_DISABLED", text)

    def test_cutover_is_rollback_guarded_and_does_not_delete_old_keys(self):
        text = WORKFLOW.read_text()
        self.assertIn("phase2_cutover_rollback_completed=yes", text)
        self.assertIn("AWS_REQUIRE_ROLE_CREDENTIALS=1", text)
        self.assertIn("phase2_cutover_s3_put_probe=not_performed", text)
        self.assertNotIn("delete-access-key", text)
        self.assertNotIn("update-access-key", text)
        self.assertNotIn("iam delete", text.lower())

    def test_readiness_diagnostic_is_production_gated_and_read_only(self):
        workflow_text = READINESS_WORKFLOW.read_text()
        probe_text = READINESS_PROBE.read_text()
        combined = workflow_text + "\n" + probe_text
        self.assertIn("workflow_dispatch:", workflow_text)
        self.assertIn("environment: production", workflow_text)
        self.assertIn("phase2_role_s3_put_live_probe=not_performed_read_only", probe_text)
        self.assertNotIn("put_object(", combined)
        self.assertNotIn("delete_object(", combined)
        self.assertNotIn("create_secret(", combined)
        self.assertNotIn("update_secret(", combined)
        self.assertNotIn("systemctl restart", combined)
        self.assertNotIn("systemctl stop", combined)
        self.assertNotIn("systemctl start", combined)

    def test_readiness_diagnostic_forces_role_credential_resolution(self):
        workflow_text = READINESS_WORKFLOW.read_text()
        probe_text = READINESS_PROBE.read_text()
        for name in (
            "AWS_ACCESS_KEY_ID",
            "AWS_SECRET_ACCESS_KEY",
            "AWS_SESSION_TOKEN",
            "AWS_PROFILE",
            "AWS_DEFAULT_PROFILE",
            "AWS_SHARED_CREDENTIALS_FILE",
            "AWS_CONFIG_FILE",
            "AWS_EC2_METADATA_DISABLED",
        ):
            self.assertIn(name, probe_text)
        self.assertIn('method == "iam-role"', probe_text)
        self.assertIn('method == "container-role"', probe_text)
        self.assertIn('method_class in {"instance-role", "container-role"}', probe_text)
        self.assertIn("phase2_role_diag_blocker=no_role_credentials", probe_text)
        self.assertIn("scripts/ops/phase2_aws_role_readiness_probe.py", workflow_text)

    def test_readiness_diagnostic_validates_secret_and_s3_read_paths_without_identifier_logging(self):
        workflow_text = READINESS_WORKFLOW.read_text()
        probe_text = READINESS_PROBE.read_text()
        self.assertIn("resolve_tenant_db_password(", probe_text)
        self.assertIn("s3.head_bucket(Bucket=bucket)", probe_text)
        self.assertIn('s3.list_objects_v2(Bucket=bucket, Prefix="tenants/", MaxKeys=1)', probe_text)
        self.assertIn('s3.get_object(Bucket=bucket, Key=key, Range="bytes=0-0")', probe_text)
        self.assertIn("phase2_role_s3_head_bucket_required=no", probe_text)
        self.assertIn("s3_minimum_policy_ready(s3_list, s3_read)", probe_text)
        self.assertNotIn("print(stored", probe_text)
        self.assertNotIn("print(bucket", probe_text)
        self.assertNotIn("print(key", probe_text)
        self.assertNotIn("print(arn", probe_text)
        self.assertIn("expected_probe_blob=", workflow_text)

    def test_readiness_workflow_pins_current_reviewed_probe_blob(self):
        text = READINESS_WORKFLOW.read_text()
        self.assertEqual(
            _expected_blob(text, "expected_probe_blob"),
            _git_blob_sha(READINESS_PROBE),
        )

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

    def test_release_ruleset_template_locks_stage_b_contract(self):
        payload = json.loads(RULESET_TEMPLATE.read_text())
        self.assertEqual(payload["target"], "branch")
        self.assertEqual(payload["enforcement"], "active")
        self.assertEqual(payload["bypass_actors"], [])
        self.assertEqual(
            payload["conditions"]["ref_name"]["include"],
            ["refs/heads/release/stabilized-deploy"],
        )
        rules = {rule["type"]: rule for rule in payload["rules"]}
        self.assertIn("deletion", rules)
        self.assertIn("non_fast_forward", rules)
        self.assertIn("pull_request", rules)
        checks = rules["required_status_checks"]["parameters"]
        self.assertTrue(checks["strict_required_status_checks_policy"])
        self.assertEqual(
            [item["context"] for item in checks["required_status_checks"]],
            ["release-preflight", "migration-rehearsal", "public-https-smoke"],
        )
