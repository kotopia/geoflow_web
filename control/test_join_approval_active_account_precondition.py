from inspect import unwrap
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.test import RequestFactory, SimpleTestCase

from control.services.join_membership_approval_service import JoinMembershipApproval
from control.views_join import join_request_decide_view


class JoinApprovalActiveAccountPreconditionTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.view = unwrap(join_request_decide_view)

    def _request(self):
        request = self.factory.post("/control/join-requests/request-key/approve/")
        request.user = SimpleNamespace(
            is_authenticated=True,
            email="admin@example.invalid",
            username="admin@example.invalid",
        )
        return request

    def _join_request(self, **overrides):
        values = {
            "id": "request-key",
            "group_id": "group-key",
            "requested_email": "target@example.invalid",
            "requested_role_code": "member",
            "status": "pending",
        }
        values.update(overrides)
        return values

    def _services(self, **overrides):
        services = MagicMock()
        services.get_join_request.return_value = self._join_request()
        services.get_role_id_by_code.return_value = "role-key"
        services.group_is_active.return_value = True
        services.get_existing_user_account_by_email.return_value = {
            "id": "user-key",
            "is_active": True,
        }
        services.reject_join_request_if_pending.return_value = True
        for name, value in overrides.items():
            getattr(services, name).return_value = value
        return services

    def _call(self, services, action="approve", *, actor_user_id="admin-key"):
        request = self._request()
        with (
            patch("control.views_join.C", services),
            patch(
                "control.views_join.lookup_user_id_from_request",
                return_value=actor_user_id,
            ),
            patch("control.views_join.approve_join_membership") as approve,
            patch("control.views_join.messages") as messages,
            patch("control.views_join.redirect", side_effect=lambda target: target),
        ):
            response = self.view(request, "request-key", action)
        return response, messages, approve

    def test_existing_active_user_receives_atomic_membership_approval(self):
        services = self._services()

        response, messages, approve = self._call(services)

        self.assertEqual(response, "control:join_requests_pending")
        services.get_or_create_user_by_email.assert_not_called()
        services.create_user.assert_not_called()
        services.approve_join_request_membership.assert_not_called()
        approve.assert_called_once()
        approval = approve.call_args.args[0]
        self.assertEqual(
            approval,
            JoinMembershipApproval(
                request_id="request-key",
                user_id="user-key",
                group_id="group-key",
                role_id="role-key",
                actor_user_id="admin-key",
            ),
        )
        services.create_set_password_token.assert_not_called()
        messages.success.assert_called_once()
        self.assertEqual(messages.success.call_args.args[1], "승인 완료")

    def _assert_approval_blocked(self, services, *, actor_user_id="admin-key"):
        response, messages, approve = self._call(
            services,
            actor_user_id=actor_user_id,
        )

        self.assertEqual(response, "control:join_requests_pending")
        services.get_or_create_user_by_email.assert_not_called()
        services.create_user.assert_not_called()
        services.upsert_user_group_membership.assert_not_called()
        services.approve_join_request_membership.assert_not_called()
        services.create_set_password_token.assert_not_called()
        services.mark_join_request_status.assert_not_called()
        approve.assert_not_called()
        messages.error.assert_called_once()

    def test_missing_user_is_not_created_or_approved(self):
        services = self._services(get_existing_user_account_by_email=None)
        self._assert_approval_blocked(services)

    def test_inactive_user_receives_no_membership_or_token(self):
        services = self._services(
            get_existing_user_account_by_email={
                "id": "user-key",
                "is_active": False,
            }
        )
        self._assert_approval_blocked(services)

    def test_invalid_role_fails_before_account_or_membership_write(self):
        services = self._services(get_role_id_by_code=None)
        self._assert_approval_blocked(services)
        services.group_is_active.assert_not_called()
        services.get_existing_user_account_by_email.assert_not_called()

    def test_inactive_or_missing_group_fails_before_membership_write(self):
        for group_active in (False, None):
            with self.subTest(group_active=group_active):
                services = self._services(group_is_active=group_active)
                self._assert_approval_blocked(services)
                services.get_existing_user_account_by_email.assert_not_called()

    def test_non_pending_request_is_not_reapproved(self):
        services = self._services()
        services.get_join_request.return_value = self._join_request(status="approved")
        self._assert_approval_blocked(services)
        services.get_role_id_by_code.assert_not_called()
        services.group_is_active.assert_not_called()
        services.get_existing_user_account_by_email.assert_not_called()

    def test_missing_authenticated_central_actor_blocks_decision(self):
        services = self._services()
        self._assert_approval_blocked(services, actor_user_id=None)
        services.get_role_id_by_code.assert_not_called()

    def test_reject_does_not_create_user_membership_or_token(self):
        services = self._services()

        response, messages, approve = self._call(services, action="reject")

        self.assertEqual(response, "control:join_requests_pending")
        services.get_or_create_user_by_email.assert_not_called()
        services.create_user.assert_not_called()
        services.upsert_user_group_membership.assert_not_called()
        services.create_set_password_token.assert_not_called()
        services.reject_join_request_if_pending.assert_called_once_with(
            "request-key",
            decided_by="admin-key",
        )
        services.mark_join_request_status.assert_not_called()
        approve.assert_not_called()
        messages.success.assert_called_once()

    def test_non_pending_reject_is_not_repeated(self):
        services = self._services()
        services.get_join_request.return_value = self._join_request(status="rejected")

        response, messages, approve = self._call(services, action="reject")

        self.assertEqual(response, "control:join_requests_pending")
        services.reject_join_request_if_pending.assert_not_called()
        services.upsert_user_group_membership.assert_not_called()
        services.create_set_password_token.assert_not_called()
        approve.assert_not_called()
        messages.error.assert_called_once()

    def test_approval_does_not_change_account_activation_state(self):
        services = self._services()

        self._call(services)

        services.get_existing_user_account_by_email.assert_called_once_with(
            "target@example.invalid"
        )
        services.get_or_create_user_by_email.assert_not_called()
        services.create_user.assert_not_called()
