from contextlib import nullcontext
from inspect import getsource
from pathlib import Path
from unittest import TestCase
from unittest.mock import MagicMock

from control.services.join_membership_approval_service import (
    JoinMembershipApproval,
    JoinMembershipApprovalRejected,
    SqlJoinMembershipApprovalRepository,
    approve_join_membership,
)


class JoinMembershipApprovalServiceTests(TestCase):
    def test_service_rejects_when_atomic_repository_cannot_apply(self):
        repository = MagicMock()
        repository.alias = "central"
        repository.apply.return_value = False
        approval = JoinMembershipApproval(
            request_id="request",
            user_id="user",
            group_id="group",
            role_id="role",
            actor_user_id="actor",
        )
        with self.assertRaises(JoinMembershipApprovalRejected):
            approve_join_membership(
                approval,
                repository=repository,
                atomic_context=nullcontext(),
            )

    def test_sql_rechecks_identity_group_role_and_pending_state_in_transaction(self):
        source = getsource(SqlJoinMembershipApprovalRepository.apply)
        for required in (
            "lower(signup_user.email)=lower(join_request.requested_email)",
            "signup_user.is_active=TRUE",
            "signup_user.email_verified=TRUE",
            "signup_user.password_hash IS NOT NULL",
            "pbkdf2_sha256$%",
            "bcrypt_sha256$%",
            "$2b$%",
            "active_group.id=join_request.group_id",
            "COALESCE(active_group.status",
            "requested_role.code=join_request.requested_role_code",
            "approval_actor.id=%s",
            "approval_actor.is_active=TRUE",
            "approval_actor.is_staff=TRUE",
            "join_request.status='pending'",
            "FOR UPDATE OF join_request, signup_user, active_group, requested_role, approval_actor",
            "ON CONFLICT (user_id, group_id)",
            "UPDATE join_requests",
            "RETURNING join_request.id",
        ):
            self.assertIn(required, source)


    def test_actor_is_required_for_audited_approval(self):
        repository = MagicMock()
        repository.alias = "central"
        approval = JoinMembershipApproval(
            request_id="request",
            user_id="user",
            group_id="group",
            role_id="role",
            actor_user_id=None,
        )
        with self.assertRaises(ValueError):
            approve_join_membership(
                approval,
                repository=repository,
                atomic_context=nullcontext(),
            )
        repository.apply.assert_not_called()

    def test_missing_decider_column_fails_closed_before_membership_write(self):
        source = getsource(SqlJoinMembershipApprovalRepository.apply)
        self.assertIn("if decider_column is None", source)
        self.assertIn("return False", source)

    def test_canonical_join_decider_column_is_preferred(self):
        source = getsource(SqlJoinMembershipApprovalRepository._decider_column)
        self.assertLess(source.index('"decided_by"'), source.index('"decided_by_user_id"'))

    def test_live_join_view_does_not_issue_legacy_raw_password_tokens(self):
        source = (
            Path(__file__).resolve().parent / "views_join.py"
        ).read_text(encoding="utf-8")
        self.assertNotIn("create_set_password_token", source)
        self.assertNotIn("send_set_password_email", source)
        self.assertNotIn("account_set_password", source)

    def test_live_join_view_uses_atomic_approval_service(self):
        source = (
            Path(__file__).resolve().parent / "views_join.py"
        ).read_text(encoding="utf-8")
        self.assertIn("approve_join_membership", source)
        self.assertIn("JoinMembershipApproval(", source)
        self.assertNotIn("C.approve_join_request_membership(", source)
