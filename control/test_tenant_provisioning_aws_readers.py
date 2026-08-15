from botocore.exceptions import ClientError
from django.test import SimpleTestCase

from control.services.tenant_provisioning_aws_readers import (
    AwsSecretsManagerReadOnlyCatalog,
)


class FakeSecretsManagerDescribeClient:
    def __init__(self, *, response=None, error=None):
        self.response = {} if response is None else response
        self.error = error
        self.calls = []

    def describe_secret(self, *, SecretId):
        self.calls.append(("describe_secret", SecretId))
        if self.error is not None:
            raise self.error
        return self.response


def _client_error(code):
    return ClientError(
        {
            "Error": {
                "Code": code,
                "Message": "provider detail must remain private",
            }
        },
        "DescribeSecret",
    )


class AwsSecretsManagerReadOnlyCatalogTests(SimpleTestCase):
    def test_successful_describe_means_secret_exists_without_value_read(self):
        secret_id = "geoflow/tenant-db/00000000-0000-0000-0000-000000000001/password"
        client = FakeSecretsManagerDescribeClient(
            response={
                "ARN": "arn:aws:secretsmanager:example",
                "Name": secret_id,
            }
        )
        catalog = AwsSecretsManagerReadOnlyCatalog(client)

        self.assertTrue(catalog.read_only)
        self.assertTrue(catalog.secret_exists(secret_id=secret_id))
        self.assertEqual(client.calls, [("describe_secret", secret_id)])

    def test_successful_empty_metadata_response_still_means_secret_exists(self):
        client = FakeSecretsManagerDescribeClient(response={})
        catalog = AwsSecretsManagerReadOnlyCatalog(client)

        self.assertTrue(catalog.secret_exists(secret_id="exact-secret-id"))
        self.assertEqual(client.calls, [("describe_secret", "exact-secret-id")])

    def test_only_resource_not_found_is_definitive_absence(self):
        client = FakeSecretsManagerDescribeClient(
            error=_client_error("ResourceNotFoundException")
        )
        catalog = AwsSecretsManagerReadOnlyCatalog(client)

        self.assertFalse(catalog.secret_exists(secret_id="exact-secret-id"))
        self.assertEqual(client.calls, [("describe_secret", "exact-secret-id")])

    def test_access_denied_remains_ambiguous_and_propagates_fail_closed(self):
        client = FakeSecretsManagerDescribeClient(
            error=_client_error("AccessDeniedException")
        )
        catalog = AwsSecretsManagerReadOnlyCatalog(client)

        with self.assertRaises(ClientError):
            catalog.secret_exists(secret_id="exact-secret-id")

        self.assertEqual(client.calls, [("describe_secret", "exact-secret-id")])

    def test_throttling_remains_ambiguous_and_propagates_fail_closed(self):
        client = FakeSecretsManagerDescribeClient(
            error=_client_error("ThrottlingException")
        )
        catalog = AwsSecretsManagerReadOnlyCatalog(client)

        with self.assertRaises(ClientError):
            catalog.secret_exists(secret_id="exact-secret-id")

        self.assertEqual(client.calls, [("describe_secret", "exact-secret-id")])

    def test_missing_secret_id_is_rejected_before_provider_call(self):
        client = FakeSecretsManagerDescribeClient()
        catalog = AwsSecretsManagerReadOnlyCatalog(client)

        with self.assertRaisesMessage(ValueError, "secret_id_required"):
            catalog.secret_exists(secret_id="  ")

        self.assertEqual(client.calls, [])

    def test_client_is_injected_and_required(self):
        with self.assertRaisesMessage(ValueError, "secrets_manager_client_required"):
            AwsSecretsManagerReadOnlyCatalog(None)
