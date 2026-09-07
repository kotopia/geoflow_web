from django.test import SimpleTestCase

from .realtime_auth import issue_realtime_ticket
from .websocket_security import scope_has_valid_realtime_ticket


class GisWebSocketSecurityTests(SimpleTestCase):
    def setUp(self):
        self.project_id = "11111111-1111-4111-8111-111111111401"

    def _scope(self, *, query_string=b"", headers=None):
        return {
            "type": "websocket",
            "path": f"/ws/gis/projects/{self.project_id}/",
            "query_string": query_string,
            "headers": headers or [],
        }

    def test_valid_query_ticket_allows_native_qgis_origin_bypass(self):
        token = issue_realtime_ticket(
            project_id=self.project_id,
            alias="cheonan_db",
            user_id=1,
        )
        scope = self._scope(query_string=("ticket=" + token).encode("utf-8"))
        self.assertTrue(scope_has_valid_realtime_ticket(scope))

    def test_valid_bearer_ticket_allows_native_qgis_origin_bypass(self):
        token = issue_realtime_ticket(
            project_id=self.project_id,
            alias="cheonan_db",
            user_id=1,
        )
        scope = self._scope(
            headers=[(b"authorization", ("Bearer " + token).encode("utf-8"))]
        )
        self.assertTrue(scope_has_valid_realtime_ticket(scope))

    def test_invalid_ticket_does_not_bypass_origin_validation(self):
        scope = self._scope(query_string=b"ticket=not-valid")
        self.assertFalse(scope_has_valid_realtime_ticket(scope))

    def test_other_websocket_path_does_not_bypass_origin_validation(self):
        token = issue_realtime_ticket(
            project_id=self.project_id,
            alias="cheonan_db",
            user_id=1,
        )
        scope = self._scope(query_string=("ticket=" + token).encode("utf-8"))
        scope["path"] = "/ws/other/"
        self.assertFalse(scope_has_valid_realtime_ticket(scope))
