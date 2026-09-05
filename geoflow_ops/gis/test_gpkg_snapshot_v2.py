from __future__ import annotations

import inspect
import sqlite3

from django.test import SimpleTestCase

from .gpkg_snapshot_v2 import (
    PackageField,
    PackageLayer,
    _copy_layer_rows,
    _create_feature_table,
    _init_gpkg,
    _install_rtree_triggers,
    _rtree_name,
)


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
