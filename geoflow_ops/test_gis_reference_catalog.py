from __future__ import annotations

from unittest.mock import patch
from pathlib import Path

from django.test import SimpleTestCase

from geoflow_ops.gis import reference_catalog
from geoflow_ops.gis.qgis_manifest import build_qgis_manifest


class _FakeCursor:
    def __init__(self, rows):
        self.rows = rows
        self.sql = ""
        self.params = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, sql, params=None):
        self.sql = str(sql)
        self.params = list(params or [])

    def fetchall(self):
        return list(self.rows)


class _FakeConnection:
    def __init__(self, rows):
        self.cursor_instance = _FakeCursor(rows)

    def cursor(self):
        return self.cursor_instance


class GisReferenceCatalogTests(SimpleTestCase):
    def test_catalog_reads_only_central_reference_definition_and_keeps_uuids(self):
        data={"layers":[{"id":"layer-uuid","standard_name":"WTL_VALV_PS"}],
              "fields":[{"id":"field-uuid","source_layer_id":"layer-uuid","physical_name":"test_field",
                         "standard_name":"TEST_FIELD","label":"테스트 항목"}],
              "codes":[{"id":"a-uuid","field_id":"field-uuid","code":"A","label":"항목 A","sort_order":10,"enabled":True},
                       {"id":"b-uuid","field_id":"field-uuid","code":"B","label":"항목 B","sort_order":20,"enabled":True}],
              "rules":[]}
        with patch("geoflow_ops.gis.central_definitions.central_snapshot",return_value=data):
            payload=reference_catalog.project_reference_catalog(using="tenant",standard_names={"wtl_valv_ps"})
        source=Path(reference_catalog.__file__).read_text(encoding='utf-8')
        self.assertNotIn("gis.meta_field_def",source)
        self.assertNotIn("gis.ref_code_group",source)
        self.assertEqual(payload["runtime_source"], "central.gis")
        self.assertEqual(payload["binding_count"], 1)
        self.assertEqual(payload["group_count"], 1)
        self.assertEqual(
            [row["id"] for row in payload["groups"][0]["values"]],
            ["a-uuid", "b-uuid"],
        )
        self.assertEqual(
            [row["code"] for row in payload["groups"][0]["values"]],
            ["A", "B"],
        )

    def test_empty_reference_catalog_is_valid(self):
        with patch("geoflow_ops.gis.central_definitions.central_snapshot",return_value={"layers":[],"fields":[],"codes":[],"rules":[]}):
            payload = reference_catalog.project_reference_catalog(
                using="tenant",
                standard_names={"DORO"},
            )

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["bindings"], [])
        self.assertEqual(payload["groups"], [])


class QgisReferenceManifestTests(SimpleTestCase):
    def test_manifest_advertises_runtime_reference_url_without_embedding_values(self):
        manifest = build_qgis_manifest(
            project={"id": "11111111-1111-4111-8111-111111111401", "code": "GIS-DEV-001"},
            plan={"profile": None, "capabilities": []},
            can_write=True,
            package_url="/package/",
            package_layers=[],
            realtime_supported=False,
        )

        transport = manifest["transport"]
        self.assertEqual(transport["reference_catalog_source"], "central.gis")
        self.assertFalse(transport["reference_values_embedded"])
        self.assertEqual(
            transport["reference_catalog_url"],
            "/gis/projects/11111111-1111-4111-8111-111111111401/api/reference-catalog/",
        )
