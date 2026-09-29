from unittest.mock import patch

from django.test import SimpleTestCase

from geoflow_ops.gis import workers


class _Cursor:
    def __init__(self, row):
        self.row = row
        self.sql = ""
        self.params = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def execute(self, sql, params=None):
        self.sql = str(sql)
        self.params = list(params or [])

    def fetchone(self):
        return self.row


class _Connection:
    def __init__(self, row):
        self.cursor_instance = _Cursor(row)

    def cursor(self):
        return self.cursor_instance


class WorkerContextTests(SimpleTestCase):
    def test_existing_employee_portrait_is_exposed_read_only(self):
        connection = _Connection(("attachment-id",))
        with patch.object(workers, "connections", {"tenant": connection}):
            result = workers._profile_photo_attachment_id("tenant", "employee-id")
        self.assertEqual(result, "attachment-id")
        self.assertEqual(connection.cursor_instance.params, ["employee-id"])
        self.assertIn("entity_type='employee'", connection.cursor_instance.sql)
        self.assertIn("purpose IN ('photo_thumb', 'thumb', 'photo')", connection.cursor_instance.sql)
        self.assertNotIn("INSERT", connection.cursor_instance.sql.upper())

    def test_missing_or_failed_portrait_falls_back_without_blocking(self):
        self.assertEqual(workers._profile_photo_attachment_id("tenant", None), "")
        with patch.object(workers, "connections", {}):
            self.assertEqual(
                workers._profile_photo_attachment_id("tenant", "employee-id"), ""
            )
