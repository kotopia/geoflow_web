from __future__ import annotations

import inspect
import sqlite3
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from .gpkg_snapshot_v2 import (
    PackageField,
    PackageLayer,
    _copy_layer_rows,
    _create_feature_table,
    _init_gpkg,
    _install_rtree_triggers,
    _central_layer_fields,
    _rtree_name,
)
from .gpkg import _is_spatial_data_type


class GeoPackageSnapshotV2Tests(SimpleTestCase):
    def _layer(self) -> PackageLayer:
        return PackageLayer(
            standard_name="DORO",
            physical_name="doro",
            label="도로 기준",
            domain="COMMON",
            geometry_kind="LINE",
            fields=(
                PackageField("id", "uuid", False, True, -100),
                PackageField("project_id", "uuid", False, True, -99),
                PackageField("source_type", "text", True, True, 10),
            ),
        )

    def test_feature_table_registers_rtree_extension(self):
        conn = sqlite3.connect(":memory:")
        try:
            if not conn.execute("SELECT sqlite_compileoption_used('ENABLE_RTREE')").fetchone()[0]:
                self.skipTest("SQLite RTree extension is not compiled in")
            _init_gpkg(conn)
            layer = self._layer()
            _create_feature_table(conn, layer)

            rtree_name = _rtree_name(layer)
            row = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
                (rtree_name,),
            ).fetchone()
            self.assertEqual(row[0], rtree_name)

            extension = conn.execute(
                """
                SELECT extension_name, scope
                  FROM gpkg_extensions
                 WHERE table_name='doro' AND column_name='geom'
                """
            ).fetchone()
            self.assertEqual(extension, ("gpkg_rtree_index", "write-only"))
        finally:
            conn.close()

    def test_rtree_edit_triggers_are_installed_after_bulk_load(self):
        conn = sqlite3.connect(":memory:")
        try:
            if not conn.execute("SELECT sqlite_compileoption_used('ENABLE_RTREE')").fetchone()[0]:
                self.skipTest("SQLite RTree extension is not compiled in")
            _init_gpkg(conn)
            layer = self._layer()
            _create_feature_table(conn, layer)
            _install_rtree_triggers(conn, layer)

            names = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='trigger' AND tbl_name='doro'"
                ).fetchall()
            }
            prefix = _rtree_name(layer)
            self.assertIn(prefix + "_insert", names)
            self.assertIn(prefix + "_update", names)
            self.assertIn(prefix + "_delete", names)
        finally:
            conn.close()

    def test_postgis_bbox_query_uses_box3d_constructor(self):
        source = inspect.getsource(_copy_layer_rows)
        self.assertIn("ST_XMin(Box3D(geom))", source)
        self.assertIn("ST_YMin(Box3D(geom))", source)
        self.assertIn("ST_XMax(Box3D(geom))", source)
        self.assertIn("ST_YMax(Box3D(geom))", source)
        self.assertNotIn("ST_Box3D", source)

    def test_secondary_postgis_geometry_is_not_a_scalar_package_field(self):
        self.assertTrue(_is_spatial_data_type("geometry(Point,4326)"))
        self.assertTrue(_is_spatial_data_type("geography (Point,4326)"))
        self.assertFalse(_is_spatial_data_type("text"))

        from . import gpkg, gpkg_snapshot_v2
        self.assertIn("_is_spatial_data_type(data_type)", inspect.getsource(gpkg._central_layer_fields))
        self.assertIn("_is_spatial_data_type(data_type)", inspect.getsource(gpkg_snapshot_v2._central_layer_fields))

    def test_table_visible_overrides_legacy_visible_for_qgis_attribute_table(self):
        plan={"form_definition":{"fields":[{"id":"field-uuid","layer_id":"layer-uuid",
            "field_name":"saa_cde","storage_data_type":"character varying(50)",
            "storage":{"kind":"column","key":"saa_cde"},"readonly":False,
            "visible":True,"form_visible":True,"table_visible":False,
            "display_order":10,"label":"상수관 용도","field_identifier":"SAA_CDE","unit":"",
            "widget_type":"combo","required":False,"description":""}]}}
        from . import gpkg, gpkg_snapshot_v2
        legacy = gpkg._central_layer_fields(plan,"layer-uuid")
        snapshot = gpkg_snapshot_v2._central_layer_fields(plan,"layer-uuid")
        self.assertFalse(next(row for row in legacy if row.name=="saa_cde").visible)
        self.assertFalse(next(row for row in snapshot if row.name=="saa_cde").visible)

    def test_profile_field_contract_carries_native_form_metadata(self):
        plan={"form_definition":{"fields":[{"id":"field-uuid","layer_id":"layer-uuid",
            "field_name":"saa_cde","storage_data_type":"character varying(50)",
            "storage":{"kind":"column","key":"saa_cde"},"readonly":False,"visible":True,
            "display_order":10,"label":"상수관 용도","field_identifier":"SAA_CDE","unit":"",
            "widget_type":"combo","required":True,"description":"관로 용도 코드"}]}}
        fields = _central_layer_fields(plan,"layer-uuid")
        field = next(row for row in fields if row.name == "saa_cde")
        self.assertEqual(field.standard_name, "SAA_CDE")
        self.assertEqual(field.label, "상수관 용도")
        self.assertEqual(field.code_group_key, "central:field-uuid")
        self.assertEqual(field.widget_type, "combo")
        self.assertTrue(field.required)
