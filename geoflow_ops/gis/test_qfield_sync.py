from __future__ import annotations

import datetime as dt
import inspect
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase
from django.urls import resolve, reverse

from . import qfield_sync_views


class QFieldSyncConcurrencyContractTests(SimpleTestCase):
    project_id = "11111111-1111-4111-8111-111111111401"

    def test_timestamp_lock_treats_timezone_equivalents_as_same_version(self):
        self.assertTrue(
            qfield_sync_views._timestamps_match(
                "2026-09-07T01:02:03.123456Z",
                dt.datetime(2026, 9, 7, 1, 2, 3, 123456, tzinfo=dt.timezone.utc),
            )
        )

    def test_timestamp_lock_rejects_changed_server_version(self):
        self.assertFalse(
            qfield_sync_views._timestamps_match(
                "2026-09-07T01:02:03.123Z",
                "2026-09-07T01:02:04.123+00:00",
            )
        )

    def test_qfield_changeset_route_uses_guarded_endpoint(self):
        url = reverse("gis:qfield_device_changeset_api", kwargs={"project_id": self.project_id})
        match = resolve(url)
        self.assertIs(match.func, qfield_sync_views.qfield_device_changeset_api)

    def test_guard_locks_rows_and_has_revision_fallback(self):
        source = inspect.getsource(qfield_sync_views._validate_qfield_concurrency)
        self.assertIn("FOR UPDATE", source)
        self.assertIn("base_updated_at", source)
        self.assertIn("server_changed_since_base_revision", source)

    def test_qfield_sidecar_combines_roaming_and_offline_changeset_sync(self):
        path = Path(settings.BASE_DIR) / "integrations" / "qfield" / "geoflow-field.qml"
        text = path.read_text(encoding="utf-8")
        self.assertIn("function scheduleRoaming(force)", text)
        self.assertIn("function queueChange(change)", text)
        self.assertIn("function syncNow(manual)", text)
        self.assertIn('protocol: "geoflow_qfield_changeset_v2"', text)
        self.assertIn("base_updated_at", text)
        self.assertIn("state.conflict", text)
        self.assertIn("scheduleRetry()", text)
        self.assertIn("editingStopped.connect", text)
        self.assertIn("captureSuppressed = true", text)
