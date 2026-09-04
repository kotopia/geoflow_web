from django.test import SimpleTestCase

from .qgis_manifest import build_qgis_manifest


class QgisManifestTests(SimpleTestCase):
    def test_manifest_never_exposes_direct_postgis_credentials(self):
        manifest = build_qgis_manifest(
            project={
                "id": "11111111-1111-4111-8111-111111111402",
                "code": "GIS-DEV-002",
                "name": "Water",
                "status": "in_progress",
            },
            plan={
                "profile": {"code": "GEOFLOW_DEV_BASE"},
                "capabilities": [{"code": "WATER"}],
                "layers": [
                    {
                        "standard_name": "WTL_PIPE_LM",
                        "physical_name": "wtl_pipe_lm",
                        "label": "WTL_PIPE_LM",
                        "domain": "WTL",
                        "geometry_kind": "LINE",
                        "required": False,
                    }
                ],
            },
            can_write=True,
            layer_geojson_path="/gis/projects/x/api/geojson/",
            layer_counts={"WTL_PIPE_LM": 2},
        )

        self.assertEqual(manifest["transport"]["mode"], "server_geojson_snapshot")
        self.assertFalse(manifest["transport"]["direct_postgis_credentials_exposed"])
        self.assertFalse(manifest["transport"]["editing_supported"])
        self.assertTrue(manifest["transport"]["write_authorized"])
        self.assertTrue(manifest["transport"]["empty_layer_fetch_skip_supported"])
        self.assertEqual(manifest["layer_count"], 1)
        layer = manifest["layers"][0]
        self.assertIn("layer=WTL_PIPE_LM", layer["snapshot_url"])
        self.assertIn("limit=5000", layer["snapshot_url"])
        self.assertEqual(layer["row_count"], 2)
        self.assertTrue(layer["snapshot_required"])
        self.assertFalse(layer["snapshot_editable"])
        serialized = repr(manifest).lower()
        self.assertNotIn("password", serialized)
        self.assertNotIn("db_host", serialized)
        self.assertNotIn("db_user", serialized)

    def test_manifest_marks_known_empty_layer_without_snapshot_requirement(self):
        manifest = build_qgis_manifest(
            project={"id": "p", "code": "P", "name": "P", "status": ""},
            plan={
                "profile": None,
                "capabilities": [{"code": "ROAD"}],
                "layers": [
                    {
                        "standard_name": "DORO",
                        "physical_name": "doro",
                        "label": "도로 기준",
                        "domain": "COMMON",
                        "geometry_kind": "LINE",
                        "required": False,
                    }
                ],
            },
            can_write=False,
            layer_geojson_path="/g/",
            layer_counts={"DORO": 0},
        )
        layer = manifest["layers"][0]
        self.assertEqual(layer["row_count"], 0)
        self.assertFalse(layer["snapshot_required"])

    def test_manifest_keeps_layer_plan_scope(self):
        manifest = build_qgis_manifest(
            project={"id": "p", "code": "P", "name": "P", "status": ""},
            plan={
                "profile": None,
                "capabilities": [{"code": "ROAD"}],
                "layers": [
                    {
                        "standard_name": "DORO",
                        "physical_name": "doro",
                        "label": "도로 기준",
                        "domain": "COMMON",
                        "geometry_kind": "LINE",
                        "required": False,
                    }
                ],
            },
            can_write=False,
            layer_geojson_path="/g/",
        )
        self.assertEqual([row["standard_name"] for row in manifest["layers"]], ["DORO"])
        self.assertFalse(manifest["transport"]["write_authorized"])
        self.assertIsNone(manifest["layers"][0]["row_count"])
        self.assertTrue(manifest["layers"][0]["snapshot_required"])
