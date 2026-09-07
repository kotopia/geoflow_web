from __future__ import annotations

import inspect
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase
from django.urls import reverse

from . import qfield_package
from .qfield_package import (
    QFIELD_PACKAGE_VERSION,
    QFIELD_PLUGIN_RUNTIME_VERSION,
    _qgs_xml,
    _render_qfield_plugin,
)
from .qfield_persistent import (
    QFIELD_PERSISTENT_PROTOCOL_VERSION,
    _inject_qgs_persistent_metadata,
    _inject_qml_persistent_session,
    qfield_install_id,
)


class QFieldPackageContractTests(SimpleTestCase):
    project_id = "11111111-1111-4111-8111-111111111401"

    def _qgs(self):
        return _qgs_xml(
            project={"id": self.project_id, "code": "GIS-DEV-001", "name": "GeoFlow QField"},
            layers=[{"physical_name": "doro", "standard_name": "DORO", "label": "도로", "geometry_kind": "LINE"}],
            server_url="http://127.0.0.1:8000",
            token="signed-project-ticket",
            roaming_plan_url=f"/gis/projects/{self.project_id}/api/qfield/roaming-plan/",
            roaming_cell_url=f"/gis/projects/{self.project_id}/api/qfield/roaming-cell/",
            project_center=[127.1, 36.8],
        )

    def test_package_versions_force_snapshot_delta_upgrade(self):
        self.assertEqual(QFIELD_PACKAGE_VERSION, "1.0")
        self.assertEqual(QFIELD_PLUGIN_RUNTIME_VERSION, "0.9.8")
        self.assertEqual(QFIELD_PERSISTENT_PROTOCOL_VERSION, "1.2")
        xml = self._qgs()
        self.assertIn("./geoflow-field.gpkg|layername=doro", xml)
        self.assertIn("signed-project-ticket", xml)
        self.assertIn("<authid>EPSG:4326</authid>", xml)

    def test_bootstrap_is_full_snapshot_then_delta(self):
        source = inspect.getsource(qfield_package.build_qfield_geopackage)
        self.assertIn("_copy_layer_rows(alias, conn, spec, str(project_id))", source)
        self.assertIn('"row_count": count', source)
        self.assertIn('("bootstrap_mode", "project_snapshot_then_delta")', source)
        self.assertNotIn("_install_rtree_triggers(conn, spec)", source)

    def test_reviewed_base_stays_load_safe(self):
        path = Path(settings.BASE_DIR) / "integrations" / "qfield" / "geoflow-field.qml"
        text = path.read_text(encoding="utf-8")
        self.assertIn("import org.qfield", text)
        self.assertIn("import org.qgis", text)
        self.assertIn("import Theme", text)
        self.assertNotIn("Instantiator", text)
        self.assertNotIn("Repeater", text)
        self.assertIn("function pollForLocalChanges(force)", text)
        self.assertIn("Never infer deletes from iterator absence", text)

    def test_rendered_base_keeps_qfield_42_property_compatibility(self):
        path = Path(settings.BASE_DIR) / "integrations" / "qfield" / "geoflow-field.qml"
        text = _render_qfield_plugin(path)
        self.assertIn("GeoFlow Field 0.9.8", text)
        self.assertIn("function captureFocusedFeatureForManualSync()", text)
        self.assertIn("manual sync using last edited feature", text)
        self.assertIn("let geometry = feature.geometry", text)
        self.assertIn("let fields = layer.fields", text)
        self.assertIn("String(feature.id)", text)
        self.assertIn("e.xMinimum, e.yMinimum, e.xMaximum, e.yMaximum", text)
        self.assertNotIn("feature.geometry()", text)
        self.assertNotIn("feature.id()", text)
        self.assertNotIn("layer.fields()", text)
        self.assertNotIn("e.xMinimum()", text)

    def test_persistent_runtime_claims_handoff_and_pulls_delta_without_auto_roaming(self):
        path = Path(settings.BASE_DIR) / "integrations" / "qfield" / "geoflow-field.qml"
        rendered = _render_qfield_plugin(path)
        text = _inject_qml_persistent_session(rendered)
        self.assertIn("import org.qfield.core", text)
        self.assertIn("QfFeatureModel", text)
        self.assertIn("function sessionAuthorized()", text)
        self.assertIn("function claimPendingSession(showMessage, callback)", text)
        self.assertIn("function pullDelta(manual)", text)
        self.assertIn("function applyDeltaChange(row, state)", text)
        self.assertIn("qfield_claim_token", text)
        self.assertIn("qfield_session_claim_url", text)
        self.assertIn("qfield_delta_url", text)
        self.assertIn("qfield_snapshot_revision", text)
        self.assertIn("pending GeoFlow handoff claimed", text)
        self.assertIn("delta applied count=", text)
        self.assertIn("running: false", text)
        self.assertNotIn("sessionRefreshTimer", text)
        self.assertNotIn("refreshSession(", text)
        self.assertNotIn("qfield_refresh_token", text)
        self.assertNotIn("bearerToken.slice(-24)", text)
        self.assertNotIn("function handleExternalAction(action)", text)

    def test_persistent_qgs_has_claim_delta_and_snapshot_revision_but_no_refresh_secret(self):
        install_id = qfield_install_id(self.project_id)
        persistent = _inject_qgs_persistent_metadata(
            self._qgs(),
            claim_token="claim-ticket",
            session_claim_url=f"/gis/projects/{self.project_id}/api/qfield/session-claim/",
            delta_url=f"/gis/projects/{self.project_id}/api/qfield/delta/",
            access_expires_at_ms=1234567890000,
            snapshot_revision=42,
            schema_fingerprint="abc123",
            install_id=install_id,
        )
        self.assertEqual(install_id, f"geoflow-{self.project_id}")
        self.assertIn("claim-ticket", persistent)
        self.assertIn("qfield_session_claim_url", persistent)
        self.assertIn("qfield_delta_url", persistent)
        self.assertIn("qfield_snapshot_revision", persistent)
        self.assertIn(">42<", persistent)
        self.assertIn("abc123", persistent)
        self.assertNotIn("qfield_refresh_token", persistent)

    def test_qfield_routes_are_project_scoped(self):
        package_url = reverse("gis:qfield_package_api", kwargs={"project_id": self.project_id})
        import_url = reverse("gis:qfield_package_import_api", kwargs={"project_id": self.project_id})
        status_url = reverse("gis:qfield_install_status_api", kwargs={"project_id": self.project_id})
        claim_url = reverse("gis:qfield_session_claim_api", kwargs={"project_id": self.project_id})
        delta_url = reverse("gis:qfield_device_delta_api", kwargs={"project_id": self.project_id})
        changeset_url = reverse("gis:qfield_device_changeset_api", kwargs={"project_id": self.project_id})
        self.assertEqual(package_url, f"/gis/projects/{self.project_id}/api/qfield/package/")
        self.assertEqual(import_url, f"/gis/projects/{self.project_id}/api/qfield/package-import/")
        self.assertEqual(status_url, f"/gis/projects/{self.project_id}/api/qfield/install-status/")
        self.assertEqual(claim_url, f"/gis/projects/{self.project_id}/api/qfield/session-claim/")
        self.assertEqual(delta_url, f"/gis/projects/{self.project_id}/api/qfield/delta/")
        self.assertEqual(changeset_url, f"/gis/projects/{self.project_id}/api/qfield/changesets/")
