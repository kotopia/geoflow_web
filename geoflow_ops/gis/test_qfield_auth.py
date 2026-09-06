from __future__ import annotations

from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

from .qfield_auth import (
    bearer_token_from_request,
    issue_qfield_ticket,
    parse_qfield_ticket,
    qfield_ticket_runtime_enabled,
)


@override_settings(DEBUG=True)
class QFieldTicketTests(SimpleTestCase):
    project_id = "11111111-1111-4111-8111-111111111401"

    def _issue(self):
        return issue_qfield_ticket(
            project_id=self.project_id,
            alias="cheonan_db",
            group_id="90000000-0000-4000-8000-000000000201",
            user_id="1",
            email="gis-dev-admin@geoflow.invalid",
            roles=["tenant_admin"],
            perms=["maps.view", "maps.edit"],
            write_authorized=True,
        )

    def test_ticket_runtime_is_strict_dev_only(self):
        with patch.dict("os.environ", {"GEOFLOW_DEV_RUNTIME_STRICT": "1"}):
            self.assertTrue(qfield_ticket_runtime_enabled())
        with patch.dict("os.environ", {"GEOFLOW_DEV_RUNTIME_STRICT": "0"}):
            self.assertFalse(qfield_ticket_runtime_enabled())

    def test_ticket_is_project_tenant_and_identity_scoped(self):
        with patch.dict("os.environ", {"GEOFLOW_DEV_RUNTIME_STRICT": "1"}):
            token = self._issue()
            payload = parse_qfield_ticket(token, project_id=self.project_id)
        self.assertEqual(payload["alias"], "cheonan_db")
        self.assertEqual(payload["user_id"], "1")
        self.assertEqual(payload["email"], "gis-dev-admin@geoflow.invalid")
        self.assertTrue(payload["write_authorized"])
        self.assertIn("maps.view", payload["perms"])

    def test_ticket_rejects_other_project_and_tampering(self):
        with patch.dict("os.environ", {"GEOFLOW_DEV_RUNTIME_STRICT": "1"}):
            token = self._issue()
            other = parse_qfield_ticket(
                token,
                project_id="11111111-1111-4111-8111-111111111402",
            )
            tampered = parse_qfield_ticket(token + "x", project_id=self.project_id)
        self.assertIsNone(other)
        self.assertIsNone(tampered)

    def test_bearer_header_is_extracted(self):
        class Request:
            headers = {"Authorization": "Bearer abc.def"}

        self.assertEqual(bearer_token_from_request(Request()), "abc.def")
