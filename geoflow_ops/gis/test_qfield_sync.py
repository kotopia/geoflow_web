from __future__ import annotations

import datetime as dt
import inspect
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase
from django.urls import resolve, reverse

from . import qfield_sync_views, qfield_ticket_roaming_views


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

    def test_qfield_roaming_cell_route_uses_ticket_scoped_endpoint(self):
        url = reverse("gis:qfield_roaming_cell_api", kwargs={"project_id": self.project_id})
        match = resolve(url)
        self.assertIs(match.func, qfield_ticket_roaming_views.qfield_ticket_roaming_cell_api)

    def test_guard_locks_rows_and_has_revision_fallback(self):
        source = inspect.getsource(qfield_sync_views._validate_qfield_concurrency)
        self.assertIn("FOR UPDATE", source)
        self.assertIn("base_updated_at", source)
        self.assertIn("server_changed_since_base_revision", source)

    def test_native_endpoints_use_signed_project_scope_without_browser_policy_recheck(self):
        roaming_source = inspect.getsource(qfield_ticket_roaming_views._ticket_project_and_plan)
        changeset_source = inspect.getsource(qfield_sync_views._ticket_project_and_plan)
        self.assertIn('payload.get("project_id")', roaming_source)
        self.assertIn('"maps.view"', roaming_source)
        self.assertNotIn("project_access_policy", roaming_source)
        self.assertIn('payload.get("write_authorized")', changeset_source)
        self.assertNotIn("project_access_policy", changeset_source)

    def test_qfield_sidecar_combines_roaming_offline_sync_and_plan_layer_binding(self):
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
        self.assertIn("managedLayerDescriptors = plan.layers || []", text)
        self.assertIn("qgisProject.mapLayersByName(physical)", text)
        self.assertIn("bindRetryTimer", text)
        self.assertIn("xhr.status === 401", text)
        self.assertIn("xhr.status === 403", text)
        self.assertIn("GeoFlow Field 0.8", text)
