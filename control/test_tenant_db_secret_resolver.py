from unittest.mock import Mock, patch

from django.test import SimpleTestCase

from control.services.tenant_db_secret_resolver import (
    TenantDBCredentialError,
    _secretsmanager_client,
    is_tenant_db_secret_reference,
    parse_tenant_db_secret_reference,
    resolve_tenant_db_password,
)


class TenantDBSecretResolverTests(SimpleTestCase):
    def test_reference_parser_accepts_secret_id_and_json_key(self):
        reference = parse_tenant_db_secret_reference(
            "aws-secretsmanager:geoflow/tenant/acme-db#password"
        )
        self.assertEqual(reference.secret_id, "geoflow/tenant/acme-db")
        self.assertEqual(reference.json_key, "password")
        self.assertTrue(
            is_tenant_db_secret_reference(
                "aws-secretsmanager:geoflow/tenant/acme-db#password"
            )
        )

    @patch("control.services.tenant_db_secret_resolver.boto3.client")
    def test_secretsmanager_client_uses_default_credential_chain(self, mocked_client):
        _secretsmanager_client(
            {
                "AWS_REGION": "ap-northeast-2",
                "AWS_ACCESS_KEY_ID": "ci-access-key-placeholder",
                "AWS_SECRET_ACCESS_KEY": "ci-secret-key-placeholder",
                "AWS_SESSION_TOKEN": "ci-session-token-placeholder",
            }
        )

        mocked_client.assert_called_once()
        args, kwargs = mocked_client.call_args
        self.assertEqual(args, ("secretsmanager",))
        self.assertEqual(kwargs.get("region_name"), "ap-northeast-2")
        self.assertNotIn("aws_access_key_id", kwargs)
        self.assertNotIn("aws_secret_access_key", kwargs)
        self.assertNotIn("aws_session_token", kwargs)

    def test_secret_string_json_key_is_resolved_without_exposing_metadata(self):
        client = Mock()
        client.get_secret_value.return_value = {
            "SecretString": '{"password":"resolved-value"}'
        }
        resolved = resolve_tenant_db_password(
            "aws-secretsmanager:geoflow/tenant/acme-db#password",
            environ={"AWS_REGION": "ap-northeast-2", "TENANT_DB_REQUIRE_SECRET_REFERENCES": "1"},
            client=client,
        )
        self.assertEqual(resolved, "resolved-value")
        client.get_secret_value.assert_called_once_with(
            SecretId="geoflow/tenant/acme-db"
        )

    def test_plaintext_is_rejected_when_secret_references_are_required(self):
        with self.assertRaises(TenantDBCredentialError):
            resolve_tenant_db_password(
                "legacy-plaintext",
                environ={"TENANT_DB_REQUIRE_SECRET_REFERENCES": "1"},
            )

    def test_plaintext_remains_compatible_before_cutover(self):
        resolved = resolve_tenant_db_password(
            "legacy-plaintext",
            environ={"TENANT_DB_REQUIRE_SECRET_REFERENCES": "0"},
        )
        self.assertEqual(resolved, "legacy-plaintext")

    def test_invalid_reference_never_falls_back_to_plaintext(self):
        with self.assertRaises(TenantDBCredentialError):
            resolve_tenant_db_password(
                "aws-secretsmanager:#password",
                environ={"TENANT_DB_REQUIRE_SECRET_REFERENCES": "0"},
            )
