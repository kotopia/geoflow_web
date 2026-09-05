from django.test import SimpleTestCase

from .qgis_manifest import build_qgis_manifest


class QgisManifestTests(SimpleTestCase):
    def _package_layers(self):
        return [
            {
                "standard_name": "WTL_PIPE_LM",
                "physical_name": "wtl_pipe_lm",
                "label": "WTL_PIPE_LM",
                "domain": "WTL",
                "geometry_kind": "LINE",
                "fields": [
                    {"name": "id", "data_type": "uuid", "editable": False, "visible": True, "sort_order": 1},
                    {"name": "project_id", "data_type": "uuid", "editable": False, "visible": True, "sort_order": 2},
                    {"name": "description", "data_type": "text", "editable": True, "visible": True, "sort_order": 3},
                ],
            }
        ]

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
            },
            can_write=True,
            package_url="/gis/projects/x/api/qgis-package/",
            package_layers=self._package_layers(),
            layer_counts={"WTL_PIPE_LM": 2},
            sync_url="/gis/projects/x/api/qgis-sync/",
            sync_supported=True,
            changeset_url="/gis/projects/x/api/changesets/",
            delta_url="/gis/projects/x/api/delta/",
            changeset_supported=True,
            current_revision=42,
            realtime_supported=True,
        )

        self.assertEqual(manifest["manifest_version"], "0.7")
        self.assertEqual(manifest["transport"]["mode"], "server_gpkg_editable_snapshot")
        self.assertFalse(manifest["transport"]["direct_postgis_credentials_exposed"])
        self.assertTrue(manifest["transport"]["local_editing_supported"])
        self.assertTrue(manifest["transport"]["sync_supported"])
        self.assertTrue(manifest["transport"]["changeset_supported"])
        self.assertTrue(manifest["transport"]["auto_sync_on_qgis_save"])
        self.assertEqual(
            manifest["transport"]["sync_strategy"],
            "field_patch_last_successful_server_write_wins",
        )
        self.assertEqual(
            manifest["transport"]["preferred_sync_protocol"],
            "changeset_v1",
        )
        self.assertEqual(manifest["transport"]["current_revision"], 42)
        self.assertEqual(manifest["transport"]["sync_url"], "/gis/projects/x/api/qgis-sync/")
        self.assertEqual(
            manifest["transport"]["changeset_url"],
            "/gis/projects/x/api/changesets/",
        )
        self.assertEqual(
            manifest["transport"]["delta_url"],
            "/gis/projects/x/api/delta/",
        )
        self.assertTrue(manifest["transport"]["realtime_supported"])
        self.assertEqual(
            manifest["transport"]["realtime_url"],
            "/ws/gis/projects/11111111-1111-4111-8111-111111111402/",
        )
        self.assertEqual(
            manifest["transport"]["realtime_protocol"],
            "websocket_delta_hint_v1",
        )
        self.assertTrue(manifest["transport"]["write_authorized"])
        self.assertEqual(manifest["transport"]["package_downloads_per_open"], 1)
        self.assertEqual(manifest["transport"]["package_url"], "/gis/projects/x/api/qgis-package/")
        self.assertEqual(manifest["layer_count"], 1)
        layer = manifest["layers"][0]
        self.assertEqual(layer["row_count"], 2)
        self.assertEqual(layer["primary_key"], "id")
        self.assertEqual(layer["local_fid"], "fid")
        self.assertEqual(layer["fields"][2]["name"], "description")
        serialized = repr(manifest).lower()
        self.assertNotIn("password", serialized)
        self.assertNotIn("db_host", serialized)
        self.assertNotIn("db_user", serialized)

    def test_manifest_disables_sync_for_read_only_user(self):
        layers = [
            {
                "standard_name": "DORO",
                "physical_name": "doro",
                "label": "도로 기준",
                "domain": "COMMON",
                "geometry_kind": "LINE",
                "fields": [],
            }
        ]
        manifest = build_qgis_manifest(
            project={"id": "p", "code": "P", "name": "P", "status": ""},
            plan={"profile": None, "capabilities": [{"code": "ROAD"}]},
            can_write=False,
            package_url="/g/pkg/",
            package_layers=layers,
            layer_counts={"DORO": 0},
            sync_url="/g/sync/",
            sync_supported=True,
            changeset_url="/g/changesets/",
            delta_url="/g/delta/",
            changeset_supported=True,
            current_revision=9,
            realtime_supported=True,
        )
        self.assertFalse(manifest["transport"]["local_editing_supported"])
        self.assertFalse(manifest["transport"]["sync_supported"])
        self.assertFalse(manifest["transport"]["changeset_supported"])
        self.assertFalse(manifest["transport"]["auto_sync_on_qgis_save"])
        self.assertEqual(manifest["transport"]["sync_url"], "")
        self.assertEqual(manifest["transport"]["changeset_url"], "")
        self.assertFalse(manifest["transport"]["realtime_supported"])
        self.assertEqual(manifest["transport"]["realtime_url"], "")
        self.assertFalse(manifest["transport"]["write_authorized"])
        self.assertEqual(manifest["layers"][0]["row_count"], 0)

    def test_manifest_uses_gpkg_fallback_until_changeset_support_is_ready(self):
        manifest = build_qgis_manifest(
            project={"id": "p", "code": "P", "name": "P", "status": ""},
            plan={"profile": None, "capabilities": [{"code": "WATER"}]},
            can_write=True,
            package_url="/g/pkg/",
            package_layers=self._package_layers(),
            sync_url="/g/sync/",
            sync_supported=True,
            changeset_url="/g/changesets/",
            delta_url="/g/delta/",
            changeset_supported=False,
            realtime_supported=True,
        )
        self.assertTrue(manifest["transport"]["local_editing_supported"])
        self.assertTrue(manifest["transport"]["sync_supported"])
        self.assertFalse(manifest["transport"]["changeset_supported"])
        self.assertTrue(manifest["transport"]["auto_sync_on_qgis_save"])
        self.assertFalse(manifest["transport"]["realtime_supported"])
        self.assertEqual(
            manifest["transport"]["preferred_sync_protocol"],
            "gpkg_diff_fallback",
        )

    def test_manifest_disables_all_write_sync_when_runtime_gate_is_off(self):
        manifest = build_qgis_manifest(
            project={"id": "p", "code": "P", "name": "P", "status": ""},
            plan={"profile": None, "capabilities": [{"code": "WATER"}]},
            can_write=True,
            package_url="/g/pkg/",
            package_layers=self._package_layers(),
            sync_url="/g/sync/",
            sync_supported=False,
            changeset_url="/g/changesets/",
            delta_url="/g/delta/",
            changeset_supported=False,
            realtime_supported=True,
        )
        self.assertTrue(manifest["transport"]["local_editing_supported"])
        self.assertFalse(manifest["transport"]["sync_supported"])
        self.assertFalse(manifest["transport"]["changeset_supported"])
        self.assertFalse(manifest["transport"]["auto_sync_on_qgis_save"])
        self.assertFalse(manifest["transport"]["realtime_supported"])
        self.assertEqual(manifest["transport"]["sync_url"], "")

    def test_manifest_keeps_layer_plan_scope(self):
        manifest = build_qgis_manifest(
            project={"id": "p", "code": "P", "name": "P", "status": ""},
            plan={"profile": None, "capabilities": [{"code": "ROAD"}]},
            can_write=False,
            package_url="/g/pkg/",
            package_layers=[
                {
                    "standard_name": "DORO",
                    "physical_name": "doro",
                    "label": "도로 기준",
                    "domain": "COMMON",
                    "geometry_kind": "LINE",
                    "fields": [],
                }
            ],
            realtime_supported=False,
        )
        self.assertEqual([row["standard_name"] for row in manifest["layers"]], ["DORO"])
        self.assertIsNone(manifest["layers"][0]["row_count"])
