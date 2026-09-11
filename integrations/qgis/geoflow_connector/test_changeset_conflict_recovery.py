from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
import uuid
from pathlib import Path

from .changeset_queue import (
    ensure_changeset_tables,
    prepare_outbox,
    repair_uuid_exists_outbox,
)
from .client import GeoFlowChangesetConflict


CLIENT_ID = "11111111-1111-4111-8111-111111111111"
OBJECT_ID = "22222222-2222-4222-8222-222222222222"


class ChangesetConflictRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.path = Path(self.tempdir.name) / "project.gpkg"
        conn = sqlite3.connect(self.path)
        try:
            conn.execute("CREATE TABLE _geoflow_package(key TEXT PRIMARY KEY, value TEXT)")
            conn.execute(
                "INSERT INTO _geoflow_package VALUES ('last_applied_revision','7')"
            )
            conn.commit()
        finally:
            conn.close()
        ensure_changeset_tables(str(self.path))
        conn = sqlite3.connect(self.path)
        try:
            conn.execute(
                """
                INSERT INTO _geoflow_pending_change(
                    layer_name, object_id, action, attributes_json,
                    geometry_wkb, updated_at
                ) VALUES (?,?,?,?,?,?)
                """,
                (
                    "WTL_PIPE_LM",
                    OBJECT_ID,
                    "create",
                    json.dumps({"saa_cde": "배수관", "pip_dip": 100}),
                    "0102abcd",
                    "2026-09-11T00:00:00+00:00",
                ),
            )
            conn.commit()
        finally:
            conn.close()

    def tearDown(self):
        self.tempdir.cleanup()

    def test_duplicate_create_is_repaired_as_update_without_losing_payload(self):
        old_id, old_payload = prepare_outbox(str(self.path), client_id=CLIENT_ID)
        repaired = repair_uuid_exists_outbox(
            str(self.path),
            old_id,
            [
                {
                    "layer": "WTL_PIPE_LM",
                    "id": OBJECT_ID,
                    "reason": "uuid_already_exists",
                }
            ],
        )
        self.assertIsNotNone(repaired)
        new_id, payload = repaired
        self.assertNotEqual(new_id, old_id)
        self.assertEqual(payload["base_revision"], 7)
        self.assertEqual(
            payload["changes"],
            [
                {
                    **old_payload["changes"][0],
                    "action": "update",
                }
            ],
        )
        self.assertEqual(payload["changes"][0]["attributes"]["saa_cde"], "배수관")
        self.assertEqual(payload["changes"][0]["geometry_wkb"], "0102abcd")

    def test_unknown_conflict_keeps_durable_outbox_unchanged(self):
        changeset_id, payload = prepare_outbox(str(self.path), client_id=CLIENT_ID)
        repaired = repair_uuid_exists_outbox(
            str(self.path),
            changeset_id,
            [{"layer": "WTL_PIPE_LM", "id": OBJECT_ID, "reason": "server_object_missing"}],
        )
        self.assertIsNone(repaired)
        conn = sqlite3.connect(self.path)
        try:
            row = conn.execute(
                "SELECT changeset_id, payload_json FROM _geoflow_outbox"
            ).fetchone()
        finally:
            conn.close()
        self.assertEqual(row[0], changeset_id)
        self.assertEqual(json.loads(row[1]), payload)

    def test_conflict_error_exposes_identity_and_reason(self):
        error = GeoFlowChangesetConflict(
            "conflict",
            conflicts=[
                {
                    "layer": "WTL_PIPE_LM",
                    "id": OBJECT_ID,
                    "reason": "uuid_already_exists",
                }
            ],
            payload={"ok": False},
        )
        self.assertEqual(error.conflicts[0]["id"], OBJECT_ID)
        self.assertIn("WTL_PIPE_LM", str(error))
        self.assertIn("uuid_already_exists", str(error))

    def test_successful_changeset_path_refreshes_baseline_only_when_queues_empty(self):
        source = (Path(__file__).resolve().parent / "plugin.py").read_text(
            encoding="utf-8"
        )
        method = source.split("def _sync_changesets", 1)[1].split(
            "def _sync_active_project", 1
        )[0]
        self.assertIn("pending_count(package_path) == 0", method)
        self.assertIn("outbox_count(package_path) == 0", method)
        self.assertIn("self._refresh_local_baseline", method)


if __name__ == "__main__":
    unittest.main()
