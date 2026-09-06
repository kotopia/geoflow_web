from django.test import SimpleTestCase

from .realtime_auth import (
    bearer_token_from_headers,
    issue_realtime_ticket,
    parse_realtime_ticket,
)


class GisRealtimeAuthTests(SimpleTestCase):
    def test_ticket_is_project_and_tenant_scoped(self):
        project_id = "11111111-1111-4111-8111-111111111401"
        token = issue_realtime_ticket(
            project_id=project_id,
            alias="cheonan_db",
            user_id=1,
        )
        payload = parse_realtime_ticket(token, project_id=project_id)
        self.assertEqual(payload["project_id"], project_id)
        self.assertEqual(payload["alias"], "cheonan_db")
        self.assertEqual(payload["user_id"], "1")

    def test_ticket_rejects_other_project(self):
        token = issue_realtime_ticket(
            project_id="11111111-1111-4111-8111-111111111401",
            alias="cheonan_db",
            user_id=1,
        )
        self.assertIsNone(
            parse_realtime_ticket(
                token,
                project_id="11111111-1111-4111-8111-111111111402",
            )
        )

    def test_ticket_rejects_tampering(self):
        project_id = "11111111-1111-4111-8111-111111111401"
        token = issue_realtime_ticket(
            project_id=project_id,
            alias="cheonan_db",
            user_id=1,
        )
        self.assertIsNone(parse_realtime_ticket(token + "x", project_id=project_id))

    def test_bearer_header_is_extracted_case_insensitively(self):
        headers = [
            (b"host", b"127.0.0.1:8000"),
            (b"authorization", b"Bearer signed-ticket"),
        ]
        self.assertEqual(bearer_token_from_headers(headers), "signed-ticket")
