import os
from unittest.mock import patch

from django.test import SimpleTestCase

from geoflow_ops.services.s3_service import get_s3_client


class S3DefaultCredentialChainTests(SimpleTestCase):
    @patch("geoflow_ops.services.s3_service.boto3.client")
    def test_static_credential_environment_is_not_forwarded_explicitly(self, mocked_client):
        with patch.dict(
            os.environ,
            {
                "AWS_ACCESS_KEY_ID": "ci-access-key-placeholder",
                "AWS_SECRET_ACCESS_KEY": "ci-secret-key-placeholder",
                "AWS_SESSION_TOKEN": "ci-session-token-placeholder",
                "AWS_REGION": "ap-northeast-2",
            },
            clear=False,
        ):
            get_s3_client()

        mocked_client.assert_called_once()
        args, kwargs = mocked_client.call_args
        self.assertEqual(args, ("s3",))
        self.assertEqual(kwargs.get("region_name"), "ap-northeast-2")
        self.assertNotIn("aws_access_key_id", kwargs)
        self.assertNotIn("aws_secret_access_key", kwargs)
        self.assertNotIn("aws_session_token", kwargs)

    @patch("geoflow_ops.services.s3_service.boto3.client")
    def test_default_region_remains_seoul(self, mocked_client):
        with patch.dict(os.environ, {}, clear=True):
            get_s3_client()

        _, kwargs = mocked_client.call_args
        self.assertEqual(kwargs.get("region_name"), "ap-northeast-2")
