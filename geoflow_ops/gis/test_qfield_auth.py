from __future__ import annotations

from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

from .qfield_auth import (
    QFIELD_CLAIM_MAX_AGE_SECONDS,
    QFIELD_HANDOFF_MAX_AGE_SECONDS,
    QFIELD_TICKET_MAX_AGE_SECONDS,
    bearer_token_from_request,
    issue_qfield_claim_token,
    issue_qfield_handoff_token,
    issue_qfield_package_import_token,
    issue_qfield_ticket,
    parse_qfield_claim_token,
    parse_qfield_handoff_token,
    parse_qfield_package_import_token,
    parse_qfield_ticket,
    qfield_ticket_runtime_enabled,
)


@override_settings(DEBUG=True)
class QFieldTicketTests(SimpleTestCase):
    project_id = "11111111-1111-4111-8111-111111111401"

    def _identity(self):
        return {
            "project_id": self.project_id,
            "alias": "cheonan_db",
            "group_id": "90000000-0000-4000-8000-000000000201",
            "user_id": "1",
            "email": "gis-dev-admin@geoflow.invalid",
            "roles": ["tenant_admin"],
            "perms": ["maps.view", "maps.edit"],
        }

    def _issue(self):
        return issue_qfield_ticket(**self._identity(), write_authorized=True)

    def test_ticket_runtime_is_strict_dev_only(self):
        with patch.dict("os.environ", {"GEOFLOW_DEV_RUNTIME_STRICT": "1"}):
            self.assertTrue(qfield_ticket_runtime_enabled())
        with patch.dict("os.environ", {"GEOFLOW_DEV_RUNTIME_STRICT": "0"}):
            self.assertFalse(qfield_ticket_runtime_enabled())

    def test_access_ticket_is_fixed_twelve_hours_and_not_refreshable(self):
        self.assertEqual(QFIELD_TICKET_MAX_AGE_SECONDS, 12 * 60 * 60)
        with patch.dict("os.environ", {"GEOFLOW_DEV_RUNTIME_STRICT": "1"}):
            token = self._issue()
            payload = parse_qfield_ticket(token, project_id=self.project_id)
        self.assertEqual(payload["alias"], "cheonan_db")
        self.assertTrue(payload["write_authorized"])

    def test_handoff_is_five_minutes_and_not_an_access_ticket(self):
        self.assertEqual(QFIELD_HANDOFF_MAX_AGE_SECONDS, 5 * 60)
        with patch.dict("os.environ", {"GEOFLOW_DEV_RUNTIME_STRICT": "1"}):
            token = issue_qfield_handoff_token(**self._identity(), write_authorized=True)
            payload = parse_qfield_handoff_token(token, project_id=self.project_id)
            as_access = parse_qfield_ticket(token, project_id=self.project_id)
        self.assertEqual(payload["purpose"], "qfield_session_handoff")
        self.assertTrue(payload["write_authorized"])
        self.assertIsNone(as_access)

    def test_claim_credential_has_no_roles_perms_and_cannot_authenticate_gis(self):
        self.assertEqual(QFIELD_CLAIM_MAX_AGE_SECONDS, 180 * 24 * 60 * 60)
        identity = self._identity()
        with patch.dict("os.environ", {"GEOFLOW_DEV_RUNTIME_STRICT": "1"}):
            token = issue_qfield_claim_token(
                project_id=identity["project_id"],
                alias=identity["alias"],
                group_id=identity["group_id"],
                user_id=identity["user_id"],
                email=identity["email"],
            )
            payload = parse_qfield_claim_token(token, project_id=self.project_id)
            as_access = parse_qfield_ticket(token, project_id=self.project_id)
            as_handoff = parse_qfield_handoff_token(token, project_id=self.project_id)
        self.assertEqual(payload["purpose"], "qfield_install_claim")
        self.assertEqual(payload["roles"], [])
        self.assertEqual(payload["perms"], [])
        self.assertIsNone(as_access)
        self.assertIsNone(as_handoff)

    def test_tokens_are_project_scoped(self):
        with patch.dict("os.environ", {"GEOFLOW_DEV_RUNTIME_STRICT": "1"}):
            token = self._issue()
            self.assertIsNone(
                parse_qfield_ticket(token, project_id="11111111-1111-4111-8111-111111111402")
            )
            self.assertIsNone(parse_qfield_ticket(token + "x", project_id=self.project_id))

    def test_package_import_token_is_purpose_scoped(self):
        with patch.dict("os.environ", {"GEOFLOW_DEV_RUNTIME_STRICT": "1"}):
            token = issue_qfield_package_import_token(**self._identity())
            payload = parse_qfield_package_import_token(token, project_id=self.project_id)
            wrong_purpose = parse_qfield_package_import_token(self._issue(), project_id=self.project_id)
        self.assertEqual(payload["purpose"], "qfield_package_import")
        self.assertIsNone(wrong_purpose)

    def test_bearer_header_is_extracted(self):
        class Request:
            headers = {"Authorization": "Bearer abc.def"}

        self.assertEqual(bearer_token_from_request(Request()), "abc.def")
