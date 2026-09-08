from __future__ import annotations

from unittest.mock import patch

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
    def test_catalog_reads_only_gis_reference_tables_and_groups_values(self):
        connection = _FakeConnection(
            [
                (
                    "WTL_VALV_PS",
                    "TEST_FIELD",
                    "test_field",
                    "테스트 항목",
                    "WTL.TEST.GROUP",
                    "테스트 코드",
                    "A",
                    "항목 A",
                    10,
                ),
                (
                    "WTL_VALV_PS",
                    "TEST_FIELD",
                    "test_field",
                    "테스트 항목",
                    "WTL.TEST.GROUP",
                    "테스트 코드",
                    "B",
                    "항목 B",
                    20,
                ),
            ]
        )
        with patch.object(reference_catalog, "connections", {"tenant": connection}):
            payload = reference_catalog.project_reference_catalog(
                using="tenant",
                standard_names={"wtl_valv_ps"},
            )

        sql = connection.cursor_instance.sql.lower()
        self.assertIn("gis.meta_field_def", sql)
        self.assertIn("gis.ref_code_group", sql)
        self.assertIn("gis.ref_code_value", sql)
        self.assertNotIn("ops.settings_nodes", sql)
        self.assertNotIn(" from ops.", sql)
        self.assertEqual(connection.cursor_instance.params, ["WTL_VALV_PS"])
        self.assertEqual(payload["runtime_source"], "gis")
        self.assertEqual(payload["binding_count"], 1)
        self.assertEqual(payload["group_count"], 1)
        self.assertEqual(
            [row["code"] for row in payload["groups"][0]["values"]],
            ["A", "B"],
        )

    def test_empty_reference_catalog_is_valid(self):
        connection = _FakeConnection([])
        with patch.object(reference_catalog, "connections", {"tenant": connection}):
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
        self.assertEqual(transport["reference_catalog_source"], "gis")
        self.assertFalse(transport["reference_values_embedded"])
        self.assertEqual(
            transport["reference_catalog_url"],
            "/gis/projects/11111111-1111-4111-8111-111111111401/api/reference-catalog/",
        )
