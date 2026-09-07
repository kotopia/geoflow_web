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

    def test_qgs_uses_local_gpkg_and_project_scoped_roaming_config(self):
        xml = _qgs_xml(
            project={
                "id": self.project_id,
                "code": "GIS-DEV-001",
                "name": "GeoFlow QField PoC",
            },
            layers=[
                {
                    "physical_name": "doro",
                    "standard_name": "DORO",
                    "label": "도로 기준",
                    "geometry_kind": "LINE",
                }
            ],
            server_url="http://127.0.0.1:8000",
            token="signed-project-ticket",
            roaming_plan_url=f"/gis/projects/{self.project_id}/api/qfield/roaming-plan/",
            roaming_cell_url=f"/gis/projects/{self.project_id}/api/qfield/roaming-cell/",
            project_center=[127.1, 36.8],
        )
        self.assertIn("./geoflow-field.gpkg|layername=doro", xml)
        self.assertIn("signed-project-ticket", xml)
        self.assertIn(self.project_id, xml)
        self.assertIn("<authid>EPSG:4326</authid>", xml)
        self.assertIn("movement_threshold_m", xml)
        self.assertEqual(QFIELD_PACKAGE_VERSION, "0.9")
        self.assertEqual(QFIELD_PLUGIN_RUNTIME_VERSION, "0.9.7")

    def test_qfield_bootstrap_materializes_project_rows_before_roaming(self):
        source = inspect.getsource(qfield_package.build_qfield_geopackage)
        self.assertIn("_copy_layer_rows(alias, conn, spec, str(project_id))", source)
        self.assertIn('"row_count": count', source)
        self.assertIn('("bootstrap_mode", "project_snapshot_then_roaming")', source)
        self.assertNotIn("_install_rtree_triggers(conn, spec)", source)

    def test_project_sidecar_exists_and_uses_current_qfield_plugin_api(self):
        path = Path(settings.BASE_DIR) / "integrations" / "qfield" / "geoflow-field.qml"
        text = path.read_text(encoding="utf-8")
        self.assertIn("import org.qfield", text)
        self.assertIn("import org.qgis", text)
        self.assertIn("import Theme", text)
        self.assertNotIn("import org.qfield.org", text)
        self.assertNotIn("import org.qfield.core", text)
        self.assertNotIn("import org.qfield.gui", text)
        self.assertIn("iface.positioning()", text)
        self.assertIn("mapSettings.visibleExtent", text)
        self.assertIn('Authorization\", \"Bearer \" + bearerToken', text)
        self.assertIn("LayerUtils.createFeatureIteratorFromExpression", text)
        self.assertIn("GeometryUtils.createGeometryFromWkt", text)
        self.assertIn("FeatureUtils.createFeature", text)
        self.assertIn("knownCellsCsv", text)
        self.assertIn("packageTokenFingerprint", text)
        self.assertIn("function resetRoamingStateForFreshTicket()", text)
        self.assertIn("function reloadProjectConfig()", text)
        self.assertIn("function onLoadProjectEnded", text)
        self.assertNotIn("QfLayerUtils", text)
        self.assertNotIn("QfGeometryUtils", text)
        self.assertNotIn("QfFeatureUtils", text)

    def test_rendered_plugin_uses_qfield_42_properties_and_last_edited_fallback(self):
        path = Path(settings.BASE_DIR) / "integrations" / "qfield" / "geoflow-field.qml"
        text = _render_qfield_plugin(path)
        self.assertIn("GeoFlow Field 0.9.7", text)
        self.assertIn("function pollForLocalChanges(force)", text)
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
        self.assertIn("Never infer deletes from iterator absence", text)
        self.assertNotIn("poll detected delete", text)
        self.assertIn('if (xhr.status >= 500)', text)
        self.assertIn("server read unavailable; roaming will retry on next timer", text)

    def test_persistent_runtime_requires_explicit_handoff_and_sparse_roaming(self):
        path = Path(settings.BASE_DIR) / "integrations" / "qfield" / "geoflow-field.qml"
        rendered = _render_qfield_plugin(path)
        text = _inject_qml_persistent_session(rendered)
        self.assertEqual(QFIELD_PERSISTENT_PROTOCOL_VERSION, "1.1")
        self.assertIn("GeoFlowFieldAuth/", text)
        self.assertIn("function sessionAuthorized()", text)
        self.assertIn("function exchangeHandoff(handoffToken, callback)", text)
        self.assertIn("qfield_session_handoff_url", text)
        self.assertIn("qfield_access_expires_at_ms", text)
        self.assertIn("explicit GeoFlow handoff required", text)
        self.assertIn("function handleExternalAction(action)", text)
        self.assertIn("qfield://geoflow", text)
        self.assertIn("if (pos && !moved) return", text)
        self.assertIn("else if (viewport)", text)
        self.assertIn("new QField install contract detected", text)
        self.assertNotIn("refreshToken", text)
        self.assertNotIn("sessionRefreshTimer", text)
        self.assertNotIn("refreshSession(", text)
        self.assertNotIn("bearerToken.slice(-24)", text)

    def test_persistent_qgs_metadata_has_explicit_access_expiry_not_refresh_secret(self):
        xml = _qgs_xml(
            project={"id": self.project_id, "code": "GIS-DEV-001", "name": "GIS DEV"},
            layers=[],
            server_url="http://127.0.0.1:8000",
            token="access-ticket",
            roaming_plan_url=f"/gis/projects/{self.project_id}/api/qfield/roaming-plan/",
            roaming_cell_url=f"/gis/projects/{self.project_id}/api/qfield/roaming-cell/",
            project_center=None,
        )
        install_id = qfield_install_id(self.project_id)
        persistent = _inject_qgs_persistent_metadata(
            xml,
            session_handoff_url=f"/gis/projects/{self.project_id}/api/qfield/session-handoff/",
            access_expires_at_ms=1234567890000,
            schema_fingerprint="abc123",
            install_id=install_id,
        )
        self.assertEqual(install_id, f"geoflow-{self.project_id}")
        self.assertIn("qfield_session_handoff_url", persistent)
        self.assertIn("qfield_access_expires_at_ms", persistent)
        self.assertIn("1234567890000", persistent)
        self.assertIn("abc123", persistent)
        self.assertIn(install_id, persistent)
        self.assertIn(QFIELD_PERSISTENT_PROTOCOL_VERSION, persistent)
        self.assertNotIn("qfield_refresh_token", persistent)

    def test_qfield_routes_are_project_scoped(self):
        package_url = reverse("gis:qfield_package_api", kwargs={"project_id": self.project_id})
        import_url = reverse("gis:qfield_package_import_api", kwargs={"project_id": self.project_id})
        status_url = reverse("gis:qfield_install_status_api", kwargs={"project_id": self.project_id})
        handoff_url = reverse("gis:qfield_session_handoff_api", kwargs={"project_id": self.project_id})
        delta_url = reverse("gis:qfield_device_delta_api", kwargs={"project_id": self.project_id})
        changeset_url = reverse("gis:qfield_device_changeset_api", kwargs={"project_id": self.project_id})
        self.assertEqual(package_url, f"/gis/projects/{self.project_id}/api/qfield/package/")
        self.assertEqual(import_url, f"/gis/projects/{self.project_id}/api/qfield/package-import/")
        self.assertEqual(status_url, f"/gis/projects/{self.project_id}/api/qfield/install-status/")
        self.assertEqual(handoff_url, f"/gis/projects/{self.project_id}/api/qfield/session-handoff/")
        self.assertEqual(delta_url, f"/gis/projects/{self.project_id}/api/qfield/delta/")
        self.assertEqual(changeset_url, f"/gis/projects/{self.project_id}/api/qfield/changesets/")
