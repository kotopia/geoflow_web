from __future__ import annotations

import os
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path

from .snapshot_cache import (
    inspect_snapshot,
    manifest_cache_fingerprint,
    select_reusable_snapshot,
    stamp_snapshot,
)


class SnapshotCacheTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.manifest = {
            "manifest_version": "0.7",
            "project": {
                "id": "11111111-1111-4111-8111-111111111401",
                "code": "GIS-DEV-001",
            },
            "profile": {
                "id": "22222222-2222-4222-8222-222222222222",
                "code": "GEOFLOW_DEV_BASE",
            },
            "layers": [
                {
                    "standard_name": "DORO",
                    "physical_name": "doro",
                    "domain": "COMMON",
                    "geometry_kind": "LINE",
                    "fields": [
                        {"name": "id", "data_type": "uuid", "editable": False, "visible": True, "sort_order": 1},
                        {"name": "project_id", "data_type": "uuid", "editable": False, "visible": True, "sort_order": 2},
                        {"name": "source_type", "data_type": "text", "editable": True, "visible": True, "sort_order": 3},
                    ],
                }
            ],
        }

    def tearDown(self):
        self.tempdir.cleanup()

    def _package(self, name: str, *, revision: int, pending: int = 0) -> Path:
        path = self.root / name
        conn = sqlite3.connect(path)
        try:
            conn.executescript(
                """
                CREATE TABLE _geoflow_package(key TEXT PRIMARY KEY, value TEXT);
                CREATE TABLE gpkg_contents(table_name TEXT, data_type TEXT);
                CREATE TABLE doro(
                    fid INTEGER PRIMARY KEY,
                    id TEXT,
                    project_id TEXT,
                    source_type TEXT,
                    geom BLOB
                );
                CREATE TABLE rtree_doro_geom(
                    id INTEGER PRIMARY KEY,
                    minx REAL,
                    maxx REAL,
                    miny REAL,
                    maxy REAL
                );
                CREATE TABLE _geoflow_pending_change(
                    layer_name TEXT,
                    object_id TEXT,
                    action TEXT,
                    attributes_json TEXT,
                    geometry_wkb TEXT,
                    updated_at TEXT
                );
                CREATE TABLE _geoflow_outbox(
                    seq INTEGER PRIMARY KEY,
                    changeset_id TEXT,
                    client_id TEXT,
                    base_revision INTEGER,
                    payload_json TEXT,
                    created_at TEXT
                );
                """
            )
            conn.executemany(
                "INSERT INTO _geoflow_package(key,value) VALUES (?,?)",
                [
                    ("package_version", "0.6"),
                    ("project_id", self.manifest["project"]["id"]),
                    ("profile_id", self.manifest["profile"]["id"]),
                    ("profile_code", self.manifest["profile"]["code"]),
                    ("snapshot_revision", str(revision)),
                    ("last_applied_revision", str(revision)),
                ],
            )
            conn.execute(
                "INSERT INTO gpkg_contents(table_name,data_type) VALUES ('doro','features')"
            )
            for index in range(pending):
                conn.execute(
                    "INSERT INTO _geoflow_pending_change VALUES (?,?,?,?,?,?)",
                    (
                        "DORO",
                        f"00000000-0000-4000-8000-{index:012d}",
                        "update",
                        "{}",
                        None,
                        "2026-09-06T00:00:00+00:00",
                    ),
                )
            conn.commit()
        finally:
            conn.close()
        return path

    def test_matching_snapshot_is_reusable_and_stamped(self):
        path = self._package("cache.gpkg", revision=34)
        candidate = inspect_snapshot(str(path), self.manifest)
        self.assertIsNotNone(candidate)
        self.assertEqual(candidate.last_applied_revision, 34)

        stamp_snapshot(str(path), self.manifest)
        conn = sqlite3.connect(path)
        try:
            saved = conn.execute(
                "SELECT value FROM _geoflow_package WHERE key='cache_manifest_fingerprint'"
            ).fetchone()[0]
        finally:
            conn.close()
        self.assertEqual(saved, manifest_cache_fingerprint(self.manifest))

    def test_schema_change_invalidates_stamped_snapshot(self):
        path = self._package("cache.gpkg", revision=34)
        stamp_snapshot(str(path), self.manifest)
        changed = dict(self.manifest)
        changed["layers"] = [dict(self.manifest["layers"][0])]
        changed["layers"][0]["fields"] = [
            *self.manifest["layers"][0]["fields"],
            {"name": "memo", "data_type": "text", "editable": True, "visible": True, "sort_order": 4},
        ]
        self.assertIsNone(inspect_snapshot(str(path), changed))

    def test_dirty_snapshot_is_preferred_over_newer_clean_snapshot(self):
        dirty = self._package("older-dirty.gpkg", revision=30, pending=1)
        time.sleep(0.01)
        clean = self._package("newer-clean.gpkg", revision=34, pending=0)
        os.utime(clean, None)

        selected = select_reusable_snapshot(str(self.root), self.manifest)
        self.assertEqual(Path(selected.path), dirty)
        self.assertTrue(selected.dirty)

    def test_multiple_dirty_snapshots_are_not_auto_selected(self):
        self._package("dirty-a.gpkg", revision=30, pending=1)
        self._package("dirty-b.gpkg", revision=31, pending=1)
        with self.assertRaises(RuntimeError):
            select_reusable_snapshot(str(self.root), self.manifest)


if __name__ == "__main__":
    unittest.main()
