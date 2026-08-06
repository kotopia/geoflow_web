from inspect import unwrap
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.test import RequestFactory, SimpleTestCase

from control.services import central_repo
from control.services.central_repo import JoinRequestStateConflict
from control.views_join import join_request_decide_view


class _RecordingAtomic:
    def __init__(self):
        self.entered = False
        self.exit_exception_type = None

    def __enter__(self):
        self.entered = True
        return self

    def __exit__(self, exc_type, exc, traceback):
        self.exit_exception_type = exc_type
        return False


class JoinApprovalTransactionServiceTests(SimpleTestCase):
    def _connection(self, rowcount=1):
        cursor = MagicMock()
        cursor.rowcount = rowcount
        connection = MagicMock()
        connection.cursor.return_value.__enter__.return_value = cursor
        mocked_connections = MagicMock()
        mocked_connections.__getitem__.return_value = connection
        return mocked_connections, cursor

    @patch("control.services.central_repo._column_exists", return_value=True)
    @patch("control.services.central_repo.upsert_user_group_membership")
    def test_membership_and_approved_transition_share_atomic_scope(
        self,
        upsert_membership,
        _column_exists,
    ):
        atomic = _RecordingAtomic()
        mocked_connections, cursor = self._connection(rowcount=1)

        with (
            patch("control.services.central_repo.transaction.atomic", return_value=atomic),
            patch("control.services.central_repo.connections", mocked_connections),
        ):
            central_repo.approve_join_request_membership(
                "request-key",
                user_id="user-key",
                group_id="group-key",
                role_id="role-key",
                decided_by="admin-key",
            )

        self.assertTrue(atomic.entered)
        self.assertIsNone(atomic.exit_exception_type)
        upsert_membership.assert_called_once()
        self.assertIn("status='approved'", " ".join(cursor.execute.call_args.args[0].split()))
        self.assertIn("status='pending'", " ".join(cursor.execute.call_args.args[0].split()))

    @patch("control.services.central_repo._column_exists", return_value=True)
    @patch("control.services.central_repo.upsert_user_group_membership")
    def test_membership_failure_prevents_approved_transition(
        self,
        upsert_membership,
        _column_exists,
    ):
        atomic = _RecordingAtomic()
        upsert_membership.side_effect = RuntimeError("sanitized test failure")
        mocked_connections, cursor = self._connection(rowcount=1)

        with (
            patch("control.services.central_repo.transaction.atomic", return_value=atomic),
            patch("control.services.central_repo.connections", mocked_connections),
            self.assertRaises(RuntimeError),
        ):
            central_repo.approve_join_request_membership(
                "request-key",
                user_id="user-key",
                group_id="group-key",
                role_id="role-key",
            )

        self.assertIs(atomic.exit_exception_type, RuntimeError)
        cursor.execute.assert_not_called()

    @patch("control.services.central_repo._column_exists", return_value=True)
    @patch("control.services.central_repo.upsert_user_group_membership")
    def test_non_pending_transition_raises_and_rolls_back_membership(
        self,
        upsert_membership,
        _column_exists,
    ):
        atomic = _RecordingAtomic()
        mocked_connections, _ = self._connection(rowcount=0)

        with (
            patch("control.services.central_repo.transaction.atomic", return_value=atomic),
            patch("control.services.central_repo.connections", mocked_connections),
            self.assertRaises(JoinRequestStateConflict),
        ):
            central_repo.approve_join_request_membership(
                "request-key",
                user_id="user-key",
                group_id="group-key",
                role_id="role-key",
            )

        upsert_membership.assert_called_once()
        self.assertIs(atomic.exit_exception_type, JoinRequestStateConflict)


class JoinApprovalFollowUpOrderingTests(SimpleTestCase):
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

    def _services(self):
        services = MagicMock()
        services.get_join_request.return_value = {
            "id": "request-key",
            "group_id": "group-key",
            "requested_email": "target@example.invalid",
            "requested_role_code": "member",
            "status": "pending",
        }
        services.get_user_by_email.return_value = {"id": "admin-key"}
        services.get_role_id_by_code.return_value = "role-key"
        services.group_is_active.return_value = True
        services.get_existing_user_account_by_email.return_value = {
            "id": "user-key",
            "is_active": True,
        }
        return services

    def _call(self, services, mail):
        request = self._request()
        with (
            patch("control.views_join.C", services),
            patch("control.views_join.Mail", mail),
            patch("control.views_join.messages") as messages,
            patch("control.views_join.redirect", side_effect=lambda target: target),
            patch("control.views_join.reverse", return_value="/password-setup/"),
        ):
            response = self.view(request, "request-key", "approve")
        return response, messages

    def test_passwordless_user_gets_token_and_mail_after_db_approval(self):
        events = []
        services = self._services()
        services.approve_join_request_membership.side_effect = (
            lambda *args, **kwargs: events.append("db-approved")
        )
        services.user_has_password.return_value = False
        services.create_set_password_token.side_effect = (
            lambda user_id: events.append("token-created") or "token-placeholder"
        )
        mail = MagicMock()
        mail.send_set_password_email.side_effect = (
            lambda *args: events.append("mail-sent")
        )

        response, _ = self._call(services, mail)

        self.assertEqual(response, "join_requests_pending")
        self.assertEqual(events, ["db-approved", "token-created", "mail-sent"])

    def test_db_approval_failure_prevents_token_and_mail(self):
        services = self._services()
        services.approve_join_request_membership.side_effect = RuntimeError(
            "sanitized test failure"
        )
        mail = MagicMock()

        response, messages = self._call(services, mail)

        self.assertEqual(response, "join_requests_pending")
        services.user_has_password.assert_not_called()
        services.create_set_password_token.assert_not_called()
        mail.send_set_password_email.assert_not_called()
        messages.error.assert_called_once()

    def test_user_with_password_gets_no_token_or_mail(self):
        services = self._services()
        services.user_has_password.return_value = True
        mail = MagicMock()

        response, _ = self._call(services, mail)

        self.assertEqual(response, "join_requests_pending")
        services.create_set_password_token.assert_not_called()
        mail.send_set_password_email.assert_not_called()

    def test_mail_failure_does_not_reverse_committed_approval(self):
        services = self._services()
        services.user_has_password.return_value = False
        services.create_set_password_token.return_value = "token-placeholder"
        mail = MagicMock()
        mail.send_set_password_email.side_effect = RuntimeError(
            "sanitized test failure"
        )

        response, messages = self._call(services, mail)

        self.assertEqual(response, "join_requests_pending")
        services.approve_join_request_membership.assert_called_once()
        services.create_set_password_token.assert_called_once_with("user-key")
        messages.warning.assert_called_once()
        messages.success.assert_called_once()

    def test_token_failure_does_not_repeat_or_reverse_db_approval(self):
        services = self._services()
        services.user_has_password.return_value = False
        services.create_set_password_token.side_effect = RuntimeError(
            "sanitized test failure"
        )
        mail = MagicMock()

        response, messages = self._call(services, mail)

        self.assertEqual(response, "join_requests_pending")
        services.approve_join_request_membership.assert_called_once()
        mail.send_set_password_email.assert_not_called()
        messages.warning.assert_called_once()
        messages.success.assert_called_once()
