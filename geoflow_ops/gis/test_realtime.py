from django.test import SimpleTestCase

from .events import build_project_change_event, project_group_name
from .realtime_views import _parse_feature_ids


class GisRealtimeHelperTests(SimpleTestCase):
    def test_group_name_uses_canonical_uuid_hex(self):
        self.assertEqual(
            project_group_name("11111111-1111-4111-8111-111111111401"),
            "gis.project.11111111111141118111111111111401",
        )

    def test_change_event_keeps_only_refresh_metadata(self):
        event = build_project_change_event(
            {
                "project_id": "11111111-1111-4111-8111-111111111401",
                "current_revision": 19,
                "client_id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
                "changeset_id": "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
                "applied": [
                    {
                        "revision": 19,
                        "action": "update",
                        "layer": "DORO",
                        "id": "cccccccc-cccc-4ccc-8ccc-cccccccccccc",
                    }
                ],
            }
        )
        self.assertEqual(event["type"], "gis.project.change")
        self.assertEqual(event["current_revision"], 19)
        self.assertEqual(event["changes"][0]["layer"], "DORO")
        self.assertNotIn("attributes", event["changes"][0])
        self.assertNotIn("geometry_wkb", event["changes"][0])

    def test_empty_applied_changes_do_not_publish_event(self):
        self.assertIsNone(build_project_change_event({"applied": []}))

    def test_feature_ids_are_canonicalized_and_deduplicated(self):
        values = _parse_feature_ids(
            "{3144cbeb-4b28-43fc-8a35-2938260b2318},3144cbeb-4b28-43fc-8a35-2938260b2318"
        )
        self.assertEqual(values, ("3144cbeb-4b28-43fc-8a35-2938260b2318",))

    def test_feature_ids_reject_invalid_value(self):
        with self.assertRaises(ValueError):
            _parse_feature_ids("not-a-uuid")
