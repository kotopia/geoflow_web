from contextlib import nullcontext
from inspect import getsource
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from control.services.central_account_erasure_service import (
    AccountErasureResult,
    SqlCentralAccountErasureRepository,
    erase_central_account_personal_data,
)


class CentralAccountErasureServiceTests(SimpleTestCase):
    @patch(
        "control.services.central_account_erasure_service.make_password",
        return_value="!unusable-password",
    )
    def test_erasure_uses_unusable_password_and_one_transaction_contract(self, make_password):
        repository = MagicMock()
        repository.alias = "central"
        repository.erase.return_value = AccountErasureResult(mode="deleted")

        result = erase_central_account_personal_data(
            "user-id",
            repository=repository,
            atomic_context=nullcontext(),
        )

        self.assertEqual(result, AccountErasureResult(mode="deleted"))
        make_password.assert_called_once_with(None)
        repository.erase.assert_called_once_with(
            user_id="user-id",
            unusable_password_hash="!unusable-password",
        )

    def test_blank_user_id_fails_before_repository_write(self):
        repository = MagicMock()
        with self.assertRaises(ValueError):
            erase_central_account_personal_data("  ", repository=repository)
        repository.erase.assert_not_called()


class CentralAccountErasureSqlContractTests(SimpleTestCase):
    def test_sql_repository_preserves_audit_anchor_without_touching_tenant_tables(self):
        erase_source = getsource(SqlCentralAccountErasureRepository.erase)
        audit_source = getsource(SqlCentralAccountErasureRepository._has_external_audit_reference)
        anonymize_source = getsource(SqlCentralAccountErasureRepository._anonymize)
        owner_source = getsource(SqlCentralAccountErasureRepository._require_no_group_ownership)
        bridge_source = getsource(
            SqlCentralAccountErasureRepository._anonymize_django_session_bridge
        )
        join_delete_source = getsource(
            SqlCentralAccountErasureRepository._delete_join_requests_for_identity
        )
        secure_reset_source = getsource(
            SqlCentralAccountErasureRepository._delete_account_password_reset_artifacts
        )
        legacy_token_source = getsource(
            SqlCentralAccountErasureRepository._delete_legacy_password_tokens
        )
        source = "\n".join(
            (
                erase_source,
                audit_source,
                anonymize_source,
                owner_source,
                bridge_source,
                join_delete_source,
                secure_reset_source,
                legacy_token_source,
            )
        )

        for required in (
            "DELETE FROM signup_verification_delivery_outbox",
            "DELETE FROM signup_email_verification_tokens",
            "DELETE FROM signup_request_events",
            "DELETE FROM signup_requests",
            "DELETE FROM user_group_map",
            "DELETE FROM join_requests",
            "account_password_reset_delivery_outbox",
            "account_password_reset_tokens",
            "password_reset_tokens",
            "user_tokens",
            "decided_by_user_id",
            "actor_user_id",
            "decided_by",
            "decided_by_user_id",
            "owner_user_id",
            "_signup_schema_mode",
            "erased-",
            "email_verified=FALSE",
            "is_active=FALSE",
            "is_staff=FALSE",
            "except IntegrityError",
            "auth_user",
            "erased-session-",
            "is_superuser=FALSE",
        ):
            self.assertIn(required, source)

        for forbidden in (
            "employee_profile",
            "geoflow_ops",
            "cheonan_db",
            "tenant_db",
        ):
            self.assertNotIn(forbidden, source)

    def test_signup_dependencies_are_deleted_before_hard_delete_attempt(self):
        source = getsource(SqlCentralAccountErasureRepository.erase)
        outbox = source.index("DELETE FROM signup_verification_delivery_outbox")
        token = source.index("DELETE FROM signup_email_verification_tokens")
        event = source.index("DELETE FROM signup_request_events")
        request = source.index("DELETE FROM signup_requests")
        user = source.rindex("DELETE FROM users WHERE id=%s")
        self.assertLess(outbox, request)
        self.assertLess(token, request)
        self.assertLess(event, request)
        self.assertLess(request, user)

    def test_join_request_schema_compatibility_is_explicit(self):
        email_source = getsource(
            SqlCentralAccountErasureRepository._join_request_email_columns
        )
        decider_source = getsource(
            SqlCentralAccountErasureRepository._join_request_decider_columns
        )
        delete_source = getsource(
            SqlCentralAccountErasureRepository._delete_join_requests_for_identity
        )
        self.assertIn('"requested_email", "email"', email_source)
        self.assertIn('"decided_by", "decided_by_user_id"', decider_source)
        self.assertIn(" OR ", delete_source)
        self.assertIn("for decider_column in self._join_request_decider_columns", getsource(SqlCentralAccountErasureRepository._has_external_audit_reference))

    def test_signup_schema_is_legacy_compatible_only_when_fully_absent(self):
        source = getsource(SqlCentralAccountErasureRepository._signup_schema_mode)
        self.assertIn('return "complete"', source)
        self.assertIn('return "absent"', source)
        self.assertIn("partially installed", source)

    def test_erasure_branches_on_signup_schema_before_signup_queries(self):
        source = getsource(SqlCentralAccountErasureRepository.erase)
        schema_check = source.index("_signup_schema_mode")
        signup_query = source.index("SELECT id::text FROM signup_requests")
        self.assertLess(schema_check, signup_query)
        self.assertIn('signup_schema_mode == "complete"', source)

    def test_group_ownership_requires_explicit_transfer_before_erasure(self):
        source = getsource(SqlCentralAccountErasureRepository._require_no_group_ownership)
        self.assertIn("owner_user_id", source)
        self.assertIn("transfer ownership before erasure", source)


class CentralAccountDjangoBridgeErasureTests(SimpleTestCase):
    def test_django_session_bridge_is_anonymized_not_left_with_original_email(self):
        source = getsource(
            SqlCentralAccountErasureRepository._anonymize_django_session_bridge
        )
        self.assertIn("SELECT id", source)
        self.assertIn("FROM auth_user", source)
        self.assertIn("FOR UPDATE", source)
        self.assertIn("erased-session-", source)
        self.assertIn("email=''", source)
        self.assertIn("is_active=FALSE", source)
        self.assertIn("is_staff=FALSE", source)
        self.assertIn("is_superuser=FALSE", source)
        self.assertIn("last_login=NULL", source)
        self.assertNotIn("DELETE FROM auth_user", source)

    def test_bridge_deprivileging_targets_authoritative_username_mapping_only(self):
        source = getsource(
            SqlCentralAccountErasureRepository._anonymize_django_session_bridge
        )
        self.assertIn("lower(COALESCE(username, ''))=lower(%s)", source)
        self.assertIn("UPDATE auth_user", source)
        self.assertIn("SET email=''", source)
        self.assertIn("lower(COALESCE(username, ''))<>lower(%s)", source)

    def test_bridge_cleanup_happens_before_central_user_hard_delete(self):
        source = getsource(SqlCentralAccountErasureRepository.erase)
        self.assertLess(
            source.index("_anonymize_django_session_bridge"),
            source.rindex("DELETE FROM users WHERE id=%s"),
        )


class CentralAccountSecureResetErasureTests(SimpleTestCase):
    def test_erasure_cleans_current_password_reset_artifacts_when_present(self):
        source = getsource(
            SqlCentralAccountErasureRepository._delete_account_password_reset_artifacts
        )
        self.assertIn("account_password_reset_delivery_outbox", source)
        self.assertIn("account_password_reset_tokens", source)
        self.assertIn("_table_exists", source)
        self.assertIn("DELETE FROM {table} WHERE user_id=%s", source)

    def test_secure_reset_cleanup_occurs_before_audit_preserving_anonymization_or_delete(self):
        source = getsource(SqlCentralAccountErasureRepository.erase)
        cleanup = source.index("_delete_account_password_reset_artifacts")
        audit_decision = source.index("_has_external_audit_reference")
        user_delete = source.rindex("DELETE FROM users WHERE id=%s")
        self.assertLess(cleanup, audit_decision)
        self.assertLess(cleanup, user_delete)


class CentralAccountLegacyTokenErasureTests(SimpleTestCase):
    def test_erasure_cleans_both_legacy_password_token_generations_when_present(self):
        source = getsource(
            SqlCentralAccountErasureRepository._delete_legacy_password_tokens
        )
        self.assertIn('"password_reset_tokens", "user_tokens"', source)
        self.assertIn("_table_exists", source)
        self.assertIn("DELETE FROM {table} WHERE user_id=%s", source)

    def test_legacy_token_cleanup_occurs_before_final_user_delete(self):
        source = getsource(SqlCentralAccountErasureRepository.erase)
        self.assertLess(
            source.index("_delete_legacy_password_tokens"),
            source.rindex("DELETE FROM users WHERE id=%s"),
        )
