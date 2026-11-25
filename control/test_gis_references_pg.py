"""SQL migration/service rehearsal. Opt in only against the disposable CI DB."""

import importlib
import os
import unittest
from uuid import uuid4

from control.services import gis_references as refs


@unittest.skipUnless(
    os.environ.get("GEOFLOW_REFERENCES_ISOLATED_PG") == "1",
    "Disposable PostgreSQL opt-in required",
)
class ReferencePostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import psycopg2

        cls.connection = psycopg2.connect(
            host="127.0.0.1",
            port=55440,
            dbname="geoflow_forms_test",
            user="geoflow_test",
            password="geoflow_test",
            connect_timeout=5,
        )
        cls.addClassCleanup(cls.connection.close)
        cls.cur = cls.connection.cursor()
        cls.cur.execute("SELECT to_regclass('gis.reference_dataset')")
        if cls.cur.fetchone()[0]:
            raise RuntimeError("Refusing to use a populated reference catalogue")
        cls.cur.execute(
            importlib.import_module(
                "control.migrations.0011_gis_reference_datasets"
            ).SQL
        )
        cls.actor = str(uuid4())

    def setUp(self):
        self.cur.execute("SAVEPOINT reference_case")

    def tearDown(self):
        self.cur.execute("ROLLBACK TO SAVEPOINT reference_case")

    def dataset(self):
        return refs.mutate(
            self.cur,
            {
                "action": "save_dataset",
                "code": "map_sheet",
                "name": "1:1000 도엽",
                "kind": "map_sheet",
            },
            self.actor,
        )

    def test_migration_and_catalogue_round_trip(self):
        self.assertTrue(refs.ready(self.cur))
        dataset = self.dataset()
        state = refs.snapshot(self.cur)
        self.assertEqual(str(state["datasets"][0]["id"]), dataset)
        self.assertEqual(state["datasets"][0]["stored_versions"], 0)
        self.assertEqual(state["events"][0]["action"], "dataset_created")

    def test_connection_reused_and_secret_never_returned(self):
        source = refs.mutate(
            self.cur,
            {
                "action": "save_source",
                "name": "공식 API",
                "kind": "api",
                "url": "https://www.data.go.kr/",
                "secret_ref": "aws-secretsmanager:geoflow/gis/references/provider#key",
            },
            self.actor,
        )
        for code in ("legal_boundary", "admin_boundary"):
            refs.mutate(
                self.cur,
                {
                    "action": "save_dataset",
                    "code": code,
                    "name": code,
                    "kind": code,
                    "source_id": source,
                },
                self.actor,
            )
        state = refs.snapshot(self.cur)
        self.assertEqual(len(state["sources"]), 1)
        self.assertEqual(len(state["datasets"]), 2)
        self.assertNotIn("secret_ref", state["sources"][0])
        refs.mutate(
            self.cur,
            {
                "action": "save_source",
                "id": source,
                "revision": 1,
                "name": "변경",
                "kind": "api",
                "url": "https://www.data.go.kr/",
            },
            self.actor,
        )
        self.assertTrue(refs.snapshot(self.cur)["sources"][0]["credential_configured"])

    def test_versions_immutable_failure_preserves_stored_original(self):
        dataset = self.dataset()
        info = {"suffix": ".zip", "filename": "map.zip", "size": 50, "sha256": "a" * 64}
        first, key = refs.reserve_version(
            self.cur, self.actor, dataset, {"label": "v1"}, info
        )
        self.assertTrue(key.startswith(f"central/gis/references/{dataset}/"))
        refs.finish_version(self.cur, self.actor, first, True)
        second, _ = refs.reserve_version(
            self.cur, self.actor, dataset, {"label": "v2"}, info
        )
        refs.finish_version(self.cur, self.actor, second, False)
        versions = refs.versions(self.cur, dataset)
        self.assertEqual({v["status"] for v in versions}, {"stored", "failed"})
        self.assertEqual(refs.snapshot(self.cur)["datasets"][0]["stored_versions"], 1)
        self.assertNotIn("object_key", versions[0])
        with self.assertRaises(refs.ReferenceError):
            refs.finish_version(self.cur, self.actor, first, False)

    def test_duplicate_version_and_dataset_codes_fail_in_database(self):
        import psycopg2

        dataset = self.dataset()
        with self.assertRaises(psycopg2.IntegrityError):
            self.dataset()
        self.cur.execute("ROLLBACK TO SAVEPOINT reference_case")
        dataset = self.dataset()
        info = {
            "suffix": ".pdf",
            "filename": "result.pdf",
            "size": 50,
            "sha256": "a" * 64,
        }
        refs.reserve_version(self.cur, self.actor, dataset, {"label": "v1"}, info)
        with self.assertRaises(psycopg2.IntegrityError):
            refs.reserve_version(self.cur, self.actor, dataset, {"label": "v1"}, info)

    def test_revision_conflict_does_not_lose_settings(self):
        dataset = self.dataset()
        payload = {
            "action": "save_dataset",
            "id": dataset,
            "revision": 1,
            "code": "map_sheet",
            "kind": "map_sheet",
            "name": "도엽 변경",
        }
        refs.mutate(self.cur, payload, self.actor)
        with self.assertRaises(refs.ReferenceError):
            refs.mutate(self.cur, payload, self.actor)
        self.assertEqual(refs.snapshot(self.cur)["datasets"][0]["name"], "도엽 변경")

    def test_inactive_dataset_cannot_receive_version(self):
        dataset = self.dataset()
        refs.mutate(
            self.cur,
            {
                "action": "save_dataset",
                "id": dataset,
                "revision": 1,
                "code": "map_sheet",
                "kind": "map_sheet",
                "name": "도엽",
                "enabled": False,
            },
            self.actor,
        )
        with self.assertRaises(refs.ReferenceError):
            refs.reserve_version(self.cur, self.actor, dataset, {"label": "v1"}, {})


@unittest.skipUnless(
    os.environ.get("GEOFLOW_REFERENCES_ISOLATED_PG") == "1",
    "Disposable PostgreSQL opt-in required",
)
class ReferenceRolloutPostgresTests(unittest.TestCase):
    def setUp(self):
        import psycopg2

        self.connection = psycopg2.connect(
            host="127.0.0.1",
            port=55440,
            dbname="geoflow_forms_test",
            user="geoflow_test",
            password="geoflow_test",
            connect_timeout=5,
        )
        self.addCleanup(self.connection.close)
        self.cur = self.connection.cursor()
        self.cur.execute("SELECT to_regclass('gis.reference_dataset')")
        if self.cur.fetchone()[0]:
            raise RuntimeError("Refusing a populated reference catalogue")
        self.cur.execute(
            "CREATE TEMP TABLE django_migrations(app text,name text,applied timestamptz)"
        )
        self.cur.execute(
            "INSERT INTO django_migrations VALUES ('control','0010_tenant_employee_registrations',now())"
        )

    def test_narrow_rollout_is_idempotent_and_preserves_registered_data(self):
        from control.management.commands.deploy_gis_reference_datasets import (
            apply_store,
            state,
        )

        self.assertFalse(state(self.cur))
        apply_store(self.cur)
        self.assertTrue(state(self.cur))
        actor = str(uuid4())
        refs.mutate(
            self.cur,
            {
                "action": "save_dataset",
                "code": "map_sheet",
                "kind": "map_sheet",
                "name": "도엽",
            },
            actor,
        )
        apply_store(self.cur)
        self.assertEqual(refs.snapshot(self.cur)["datasets"][0]["name"], "도엽")
        self.cur.execute(
            "SELECT count(*) FROM django_migrations WHERE name='0011_gis_reference_datasets'"
        )
        self.assertEqual(self.cur.fetchone()[0], 1)

    def test_missing_prerequisite_never_applies_other_migrations(self):
        from django.core.management.base import CommandError

        from control.management.commands.deploy_gis_reference_datasets import (
            apply_store,
        )

        self.cur.execute("DELETE FROM django_migrations")
        with self.assertRaises(CommandError):
            apply_store(self.cur)
        self.cur.execute("SELECT to_regclass('gis.reference_dataset')")
        self.assertIsNone(self.cur.fetchone()[0])

    def test_partial_or_lost_schema_is_not_silently_recreated(self):
        from django.core.management.base import CommandError

        from control.management.commands.deploy_gis_reference_datasets import (
            apply_store,
            state,
        )

        self.cur.execute(
            "CREATE SCHEMA IF NOT EXISTS gis; CREATE TABLE gis.reference_source(id uuid)"
        )
        with self.assertRaises(CommandError):
            state(self.cur)
        self.cur.execute("DROP TABLE gis.reference_source")
        self.cur.execute(
            "INSERT INTO django_migrations VALUES ('control','0011_gis_reference_datasets',now())"
        )
        with self.assertRaises(CommandError):
            apply_store(self.cur)


if __name__ == "__main__":
    unittest.main()
