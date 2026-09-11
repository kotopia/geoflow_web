from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
import uuid
from pathlib import Path

from .changeset_queue import ensure_changeset_tables
from .local_change_recovery import _content_hash, recover_untracked_snapshot_changes


PROJECT_ID = "11111111-1111-4111-8111-111111111111"
EXISTING_ID = "22222222-2222-4222-8222-222222222222"
NEW_ID = "33333333-3333-4333-8333-333333333333"
DELETED_ID = "44444444-4444-4444-8444-444444444444"
WKB = bytes.fromhex(
    "01020000000200000000000000000000000000000000000000000000000000f03f000000000000f03f"
)
GPKG_GEOMETRY = b"GP\x00\x00" + (4326).to_bytes(4, "little") + WKB


class LocalChangeRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.path = Path(self.tempdir.name) / "project.gpkg"
        self.manifest = {
            "project": {"id": PROJECT_ID},
            "layers": [
                {
                    "standard_name": "WTL_PIPE_LM",
                    "physical_name": "wtl_pipe_lm",
                    "fields": [
                        {"name": "id", "editable": False},
                        {"name": "project_id", "editable": False},
                        {"name": "ftr_cde", "editable": True},
                    ],
                }
            ],
        }
        conn = sqlite3.connect(self.path)
        try:
            conn.executescript(
                """
                CREATE TABLE _geoflow_package(key TEXT PRIMARY KEY, value TEXT);
                CREATE TABLE _geoflow_baseline(
                    layer_name TEXT, object_id TEXT, local_fid INTEGER,
                    source_updated_at TEXT, content_hash TEXT
                );
                CREATE TABLE wtl_pipe_lm(
                    fid INTEGER PRIMARY KEY, id TEXT, project_id TEXT,
                    ftr_cde TEXT, geom BLOB
                );
                """
            )
            existing_attrs = {
                "id": EXISTING_ID,
                "project_id": PROJECT_ID,
                "ftr_cde": "SA001",
            }
            conn.executemany(
                "INSERT INTO wtl_pipe_lm VALUES (?,?,?,?,?)",
                [
                    (1, EXISTING_ID, PROJECT_ID, "SA001", GPKG_GEOMETRY),
                    (2, NEW_ID, PROJECT_ID, "SA002", GPKG_GEOMETRY),
                ],
            )
            conn.executemany(
                "INSERT INTO _geoflow_baseline VALUES (?,?,?,?,?)",
                [
                    (
                        "wtl_pipe_lm",
                        EXISTING_ID,
                        1,
                        "2026-09-11T00:00:00Z",
                        _content_hash(existing_attrs, WKB, ["ftr_cde"]),
                    ),
                    (
                        "wtl_pipe_lm",
                        DELETED_ID,
                        3,
                        "2026-09-11T00:00:00Z",
                        "server-hash",
                    ),
                ],
            )
            conn.commit()
        finally:
            conn.close()
        ensure_changeset_tables(str(self.path))

    def tearDown(self):
        self.tempdir.cleanup()

    def test_recovers_create_and_delete_without_requeuing_unchanged_row(self):
        result = recover_untracked_snapshot_changes(str(self.path), self.manifest)
        self.assertEqual(
            result,
            {"created": 1, "updated": 0, "deleted": 1, "total": 2},
        )
        conn = sqlite3.connect(self.path)
        try:
            rows = conn.execute(
                "SELECT object_id, action, attributes_json, geometry_wkb "
                "FROM _geoflow_pending_change ORDER BY object_id"
            ).fetchall()
        finally:
            conn.close()
        self.assertEqual(
            [row[:2] for row in rows],
            [(NEW_ID, "create"), (DELETED_ID, "delete")],
        )
        self.assertEqual(json.loads(rows[0][2]), {"ftr_cde": "SA002"})
        self.assertEqual(rows[0][3], WKB.hex())

    def test_rejects_cross_project_local_row(self):
        conn = sqlite3.connect(self.path)
        try:
            conn.execute(
                "UPDATE wtl_pipe_lm SET project_id=? WHERE id=?",
                (str(uuid.uuid4()), NEW_ID),
            )
            conn.commit()
        finally:
            conn.close()
        with self.assertRaisesRegex(RuntimeError, "다른 프로젝트"):
            recover_untracked_snapshot_changes(str(self.path), self.manifest)

    def test_qgis_save_still_schedules_automatic_changeset_sync(self):
        root = Path(__file__).resolve().parent
        plugin = (root / "plugin.py").read_text(encoding="utf-8")
        snapshot_reuse = (root / "snapshot_reuse.py").read_text(encoding="utf-8")
        self.assertIn("self._auto_sync_timer.setInterval(700)", plugin)
        self.assertIn("self._schedule_auto_sync()", plugin)
        self.assertIn("self._sync_active_project(self.active_client, automatic=True)", plugin)
        self.assertIn("layer.beforeCommitChanges.connect", snapshot_reuse)
        self.assertIn("layer.afterCommitChanges.connect", snapshot_reuse)
        self.assertIn("write_authorized and sync_supported", snapshot_reuse)


if __name__ == "__main__":
    unittest.main()
