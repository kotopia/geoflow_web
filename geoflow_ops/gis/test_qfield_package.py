from __future__ import annotations

from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase
from django.urls import reverse

from .qfield_package import _qgs_xml


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

    def test_project_sidecar_exists_and_uses_supported_qfield_utilities(self):
        path = Path(settings.BASE_DIR) / "integrations" / "qfield" / "geoflow-field.qml"
        text = path.read_text(encoding="utf-8")
        self.assertIn("iface.positioning()", text)
        self.assertIn("mapSettings.visibleExtent", text)
        self.assertIn('Authorization", "Bearer " + bearerToken', text)
        self.assertIn("QfLayerUtils.createFeatureIteratorFromExpression", text)
        self.assertIn("QfGeometryUtils.createGeometryFromWkt", text)
        self.assertIn("QfFeatureUtils.createFeature", text)
        self.assertIn("QfLayerUtils.addFeature", text)
        self.assertIn("knownCellsCsv", text)
        self.assertNotIn("GeometryUtils.createGeometryFromWkt", text.replace("QfGeometryUtils.createGeometryFromWkt", ""))

    def test_qfield_routes_are_project_scoped(self):
        package_url = reverse("gis:qfield_package_api", kwargs={"project_id": self.project_id})
        import_url = reverse("gis:qfield_package_import_api", kwargs={"project_id": self.project_id})
        delta_url = reverse("gis:qfield_device_delta_api", kwargs={"project_id": self.project_id})
        changeset_url = reverse("gis:qfield_device_changeset_api", kwargs={"project_id": self.project_id})
        self.assertEqual(
            package_url,
            f"/gis/projects/{self.project_id}/api/qfield/package/",
        )
        self.assertEqual(
            import_url,
            f"/gis/projects/{self.project_id}/api/qfield/package-import/",
        )
        self.assertEqual(
            delta_url,
            f"/gis/projects/{self.project_id}/api/qfield/delta/",
        )
        self.assertEqual(
            changeset_url,
            f"/gis/projects/{self.project_id}/api/qfield/changesets/",
        )
