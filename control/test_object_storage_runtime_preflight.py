from pathlib import Path

from django.test import SimpleTestCase

from control.services.object_storage_runtime_preflight import (
    inspect_object_storage_runtime,
)


class ObjectStorageRuntimePreflightTests(SimpleTestCase):
    def test_iam_role_configuration_passes_without_static_credentials(self):
        checks = inspect_object_storage_runtime(
            environ={
                "AWS_S3_BUCKET": "private-geoflow-bucket",
                "AWS_REGION": "ap-northeast-2",
            }
        )
        self.assertTrue(all(check.ready for check in checks))

    def test_incomplete_static_credential_pair_fails_without_echoing_value(self):
        secret = "DO_NOT_PRINT_THIS_ACCESS_KEY"
        checks = inspect_object_storage_runtime(
            environ={
                "AWS_S3_BUCKET": "private-geoflow-bucket",
                "AWS_REGION": "ap-northeast-2",
                "AWS_ACCESS_KEY_ID": secret,
            }
        )
        failures = {check.code for check in checks if not check.ready}
        rendered = "\n".join(check.message for check in checks)
        self.assertEqual(failures, {"aws_credential_pair"})
        self.assertNotIn(secret, rendered)

    def test_missing_bucket_or_wrong_region_fails(self):
        checks = inspect_object_storage_runtime(
            environ={"AWS_REGION": "us-east-1"}
        )
        failures = {check.code for check in checks if not check.ready}
        self.assertEqual(failures, {"s3_bucket_configured", "s3_region"})

    def test_role_only_guard_rejects_static_credentials_without_echoing_values(self):
        access_key = "DO_NOT_PRINT_ACCESS_KEY"
        secret_key = "DO_NOT_PRINT_SECRET_KEY"
        checks = inspect_object_storage_runtime(
            environ={
                "AWS_S3_BUCKET": "private-geoflow-bucket",
                "AWS_REGION": "ap-northeast-2",
                "AWS_REQUIRE_ROLE_CREDENTIALS": "1",
                "AWS_ACCESS_KEY_ID": access_key,
                "AWS_SECRET_ACCESS_KEY": secret_key,
            }
        )
        failures = {check.code for check in checks if not check.ready}
        rendered = "\n".join(check.message for check in checks)
        self.assertEqual(failures, {"aws_role_only_runtime"})
        self.assertNotIn(access_key, rendered)
        self.assertNotIn(secret_key, rendered)

    def test_role_only_guard_passes_when_static_and_profile_sources_are_absent(self):
        checks = inspect_object_storage_runtime(
            environ={
                "AWS_S3_BUCKET": "private-geoflow-bucket",
                "AWS_REGION": "ap-northeast-2",
                "AWS_REQUIRE_ROLE_CREDENTIALS": "true",
            }
        )
        failures = {check.code for check in checks if not check.ready}
        self.assertEqual(failures, set())
        messages = {check.code: check.message for check in checks}
        self.assertIn("enabled", messages["aws_role_only_runtime"].lower())

    def test_role_only_guard_rejects_profile_source(self):
        checks = inspect_object_storage_runtime(
            environ={
                "AWS_S3_BUCKET": "private-geoflow-bucket",
                "AWS_REGION": "ap-northeast-2",
                "AWS_REQUIRE_ROLE_CREDENTIALS": "yes",
                "AWS_PROFILE": "legacy-profile",
            }
        )
        failures = {check.code for check in checks if not check.ready}
        rendered = "\n".join(check.message for check in checks)
        self.assertEqual(failures, {"aws_role_only_runtime"})
        self.assertNotIn("legacy-profile", rendered)

    def test_phase2_runtime_probe_is_present_and_python_syntax_is_valid(self):
        probe = Path(__file__).resolve().parents[1] / "scripts" / "ops" / "phase2_role_runtime_probe.py"
        self.assertTrue(probe.is_file())
        source = probe.read_text(encoding="utf-8")
        compile(source, str(probe), "exec")
