from __future__ import annotations

import datetime as dt
import sqlite3
import tempfile
import uuid
from pathlib import Path

from django.test import SimpleTestCase

from .cache_lifecycle import (
    CacheInventoryItem,
    execute_cache_cleanup,
    inspect_cache_file,
    plan_cache_cleanup,
)


UTC = dt.timezone.utc


class CacheLifecycleTests(SimpleTestCase):
    def _item(
        self,
        *,
        project_id: str,
        days_old: int,
        status: str = "active",
        size_bytes: int = 100,
        pending: int = 0,
        outbox: int = 0,
        path: str | None = None,
    ) -> CacheInventoryItem:
        now = dt.datetime(2026, 9, 6, tzinfo=UTC)
        return CacheInventoryItem(
            path=path or f"/tmp/{project_id}.gpkg",
            project_id=project_id,
            project_status=status,
            size_bytes=size_bytes,
            last_opened_at=now - dt.timedelta(days=days_old),
            pending_count=pending,
            outbox_count=outbox,
        )

    def test_age_policy_uses_90_days_active_and_30_days_completed(self):
        now = dt.datetime(2026, 9, 6, tzinfo=UTC)
        active_old = self._item(project_id="a", days_old=91)
        active_recent = self._item(project_id="b", days_old=89)
        completed_old = self._item(
            project_id="c",
            days_old=31,
            status="completed",
        )
        completed_recent = self._item(
            project_id="d",
            days_old=29,
            status="complete",
        )
        decisions = plan_cache_cleanup(
            [active_old, active_recent, completed_old, completed_recent],
            now=now,
        )
        reasons = {row.project_id: row.reason for row in decisions}
        self.assertEqual(reasons["a"], "inactive_expired")
        self.assertEqual(reasons["c"], "completed_grace_expired")
        self.assertNotIn("b", reasons)
        self.assertNotIn("d", reasons)

    def test_dirty_pinned_and_active_paths_are_never_selected(self):
        now = dt.datetime(2026, 9, 6, tzinfo=UTC)
        dirty = self._item(project_id="dirty", days_old=400, pending=1)
        queued = self._item(project_id="queued", days_old=400, outbox=1)
        pinned = self._item(project_id="pinned", days_old=400)
        active = self._item(project_id="active", days_old=400, path="/tmp/active.gpkg")
        decisions = plan_cache_cleanup(
            [dirty, queued, pinned, active],
            now=now,
            quota_bytes=1,
            pinned_project_ids={"pinned"},
            protected_paths={"/tmp/active.gpkg"},
        )
        self.assertEqual(decisions, ())

    def test_quota_evicts_completed_then_lru_without_touching_dirty(self):
        now = dt.datetime(2026, 9, 6, tzinfo=UTC)
        completed = self._item(
            project_id="completed",
            days_old=5,
            status="completed",
            size_bytes=100,
        )
        older = self._item(project_id="older", days_old=20, size_bytes=100)
        recent = self._item(project_id="recent", days_old=2, size_bytes=100)
        dirty = self._item(project_id="dirty", days_old=500, size_bytes=100, pending=1)
        decisions = plan_cache_cleanup(
            [completed, older, recent, dirty],
            now=now,
            quota_bytes=250,
        )
        self.assertEqual([row.project_id for row in decisions], ["completed", "older"])
        self.assertTrue(all(row.reason == "quota_lru" for row in decisions))

    def test_inspect_and_execute_only_manage_geoflow_gpkg_under_root(self):
        project_id = str(uuid.uuid4())
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "projects"
            project_dir = root / project_id
            project_dir.mkdir(parents=True)
            package = project_dir / "cache.gpkg"
            conn = sqlite3.connect(package)
            try:
                conn.executescript(
                    """
                    CREATE TABLE _geoflow_package(key TEXT PRIMARY KEY, value TEXT);
                    CREATE TABLE _geoflow_pending_change(id INTEGER);
                    CREATE TABLE _geoflow_outbox(id INTEGER);
                    """
                )
                conn.executemany(
                    "INSERT INTO _geoflow_package(key,value) VALUES (?,?)",
                    [
                        ("project_id", project_id),
                        ("cache_project_status", "completed"),
                        ("cache_last_opened_at", "2026-01-01T00:00:00+00:00"),
                    ],
                )
                conn.commit()
            finally:
                conn.close()

            item = inspect_cache_file(str(package))
            self.assertIsNotNone(item)
            decisions = plan_cache_cleanup(
                [item],
                now=dt.datetime(2026, 9, 6, tzinfo=UTC),
            )
            result = execute_cache_cleanup(str(root), decisions)
            self.assertEqual(result.deleted_files, 1)
            self.assertFalse(package.exists())
