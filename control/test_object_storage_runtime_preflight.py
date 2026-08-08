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
