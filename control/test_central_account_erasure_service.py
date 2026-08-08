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
        source = "\n".join((erase_source, audit_source, anonymize_source, owner_source))

        for required in (
            "DELETE FROM signup_verification_delivery_outbox",
            "DELETE FROM signup_email_verification_tokens",
            "DELETE FROM signup_request_events",
            "DELETE FROM signup_requests",
            "DELETE FROM user_group_map",
            "DELETE FROM join_requests",
            "DELETE FROM password_reset_tokens",
            "decided_by_user_id",
            "actor_user_id",
            "decided_by",
            "owner_user_id",
            "erased-",
            "email_verified=FALSE",
            "is_active=FALSE",
            "except IntegrityError",
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

    def test_join_request_email_schema_compatibility_is_explicit(self):
        source = getsource(SqlCentralAccountErasureRepository._join_request_email_column)
        self.assertIn('"email"', source)
        self.assertIn('"requested_email"', source)

    def test_group_ownership_requires_explicit_transfer_before_erasure(self):
        source = getsource(SqlCentralAccountErasureRepository._require_no_group_ownership)
        self.assertIn("owner_user_id", source)
        self.assertIn("transfer ownership before erasure", source)
