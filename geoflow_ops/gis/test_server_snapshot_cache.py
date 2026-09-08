from __future__ import annotations

import tempfile
from pathlib import Path

from django.test import SimpleTestCase

from .server_snapshot_cache import get_or_build_server_snapshot


class _StubSnapshotBuilder:
    def __init__(self):
        self.calls = 0

    def __call__(self, alias, *, project_id, plan):
        self.calls += 1
        handle = tempfile.NamedTemporaryFile(suffix=".gpkg", delete=False)
        path = Path(handle.name)
        handle.write(b"SQLite format 3\x00" + bytes([self.calls]) * 32)
        handle.close()
        revision = int(plan.get("_test_revision") or 0)
        return (
            path,
            [
                {
                    "standard_name": "DORO",
                    "physical_name": "doro",
                    "row_count": 1,
                }
            ],
            revision,
        )


class ServerSnapshotCacheTests(SimpleTestCase):
    def setUp(self):
        self.project_id = "11111111-1111-4111-8111-111111111401"
        self.plan = {
            "profile": {
                "id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
                "code": "GEOFLOW_DEV_BASE",
            },
            "_test_revision": 7,
        }
        self.layers = [
            {
                "standard_name": "DORO",
                "physical_name": "doro",
                "domain": "COMMON",
                "geometry_kind": "LINE",
                "fields": [
                    {
                        "name": "id",
                        "data_type": "uuid",
                        "editable": False,
                        "visible": True,
                        "sort_order": 1,
                    },
                    {
                        "name": "source_type",
                        "data_type": "text",
                        "editable": True,
                        "visible": True,
                        "sort_order": 2,
                    },
                ],
            }
        ]

    def test_exact_revision_is_built_once_then_reused(self):
        builder = _StubSnapshotBuilder()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            first = get_or_build_server_snapshot(
                alias="cheonan_db",
                project_id=self.project_id,
                plan=self.plan,
                layer_manifest=self.layers,
                requested_revision=7,
                cache_root=root,
                builder=builder,
            )
            second = get_or_build_server_snapshot(
                alias="cheonan_db",
                project_id=self.project_id,
                plan=self.plan,
                layer_manifest=self.layers,
                requested_revision=7,
                cache_root=root,
                builder=builder,
            )

            self.assertEqual(builder.calls, 1)
            self.assertFalse(first.cache_hit)
            self.assertTrue(second.cache_hit)
            self.assertEqual(first.path, second.path)
            self.assertEqual(second.snapshot_revision, 7)

    def test_new_revision_builds_new_immutable_artifact(self):
        builder = _StubSnapshotBuilder()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            first = get_or_build_server_snapshot(
                alias="cheonan_db",
                project_id=self.project_id,
                plan=self.plan,
                layer_manifest=self.layers,
                requested_revision=7,
                cache_root=root,
                builder=builder,
            )
            plan8 = {**self.plan, "_test_revision": 8}
            second = get_or_build_server_snapshot(
                alias="cheonan_db",
                project_id=self.project_id,
                plan=plan8,
                layer_manifest=self.layers,
                requested_revision=8,
                cache_root=root,
                builder=builder,
            )

            self.assertEqual(builder.calls, 2)
            self.assertNotEqual(first.path, second.path)
            self.assertEqual(second.snapshot_revision, 8)
            self.assertFalse(second.cache_hit)

    def test_schema_fingerprint_change_does_not_reuse_old_package(self):
        builder = _StubSnapshotBuilder()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            first = get_or_build_server_snapshot(
                alias="cheonan_db",
                project_id=self.project_id,
                plan=self.plan,
                layer_manifest=self.layers,
                requested_revision=7,
                cache_root=root,
                builder=builder,
            )
            changed_layers = [
                {
                    **self.layers[0],
                    "fields": [
                        *self.layers[0]["fields"],
                        {
                            "name": "description",
                            "data_type": "text",
                            "editable": True,
                            "visible": True,
                            "sort_order": 3,
                        },
                    ],
                }
            ]
            second = get_or_build_server_snapshot(
                alias="cheonan_db",
                project_id=self.project_id,
                plan=self.plan,
                layer_manifest=changed_layers,
                requested_revision=7,
                cache_root=root,
                builder=builder,
            )

            self.assertEqual(builder.calls, 2)
            self.assertNotEqual(first.path, second.path)
            self.assertFalse(second.cache_hit)

    def test_artifact_is_stored_under_revision_actually_built(self):
        builder = _StubSnapshotBuilder()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            # Simulate a revision advancing after the caller read current=6 but
            # before the builder entered its REPEATABLE READ transaction.
            artifact = get_or_build_server_snapshot(
                alias="cheonan_db",
                project_id=self.project_id,
                plan=self.plan,
                layer_manifest=self.layers,
                requested_revision=6,
                cache_root=root,
                builder=builder,
            )
            reused = get_or_build_server_snapshot(
                alias="cheonan_db",
                project_id=self.project_id,
                plan=self.plan,
                layer_manifest=self.layers,
                requested_revision=7,
                cache_root=root,
                builder=builder,
            )

            self.assertEqual(artifact.snapshot_revision, 7)
            self.assertTrue(reused.cache_hit)
            self.assertEqual(builder.calls, 1)
