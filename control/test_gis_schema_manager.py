import json
import os
from pathlib import Path
import unittest
from uuid import uuid4

from control.services import gis_schema_manager as manager
from geoflow_ops.gis.form_definitions import DefinitionError


class FakeCursor:
    def __init__(self):
        self.statements = []
        self.description = []
        self._one = None

    def execute(self, statement, params=None):
        self.statements.append((str(statement), params or []))

    def fetchone(self):
        return self._one


class GisSchemaManagerValidationTests(unittest.TestCase):
    def test_identifier_accepts_only_simple_postgres_identifier(self):
        self.assertEqual(manager.identifier("wtl_manh_ps"), "wtl_manh_ps")
        self.assertEqual(manager.identifier("NEW_DEPTH"), "new_depth")
        for value in ("gis.wtl_manh_ps", "ctr.contracts", "x;drop table y", '"quoted"', "a-b"):
            with self.assertRaises(DefinitionError):
                manager.identifier(value)

    def test_data_type_is_whitelisted(self):
        for value in ("text", "varchar", "integer", "numeric", "double precision", "jsonb"):
            self.assertEqual(manager.data_type(value), value)
        for value in ("geometry", "serial", "text; drop table x", "varchar(100)", "public.text"):
            with self.assertRaises(DefinitionError):
                manager.data_type(value)

    def test_preview_is_always_gis_schema_and_not_arbitrary_sql(self):
        add = manager.preview_sql(
            operation="ADD_COLUMN",
            table_name="wtl_manh_ps",
            new_name="new_depth",
            new_type="numeric",
        )
        rename = manager.preview_sql(
            operation="RENAME_COLUMN",
            table_name="wtl_manh_ps",
            old_name="sbc_siz",
            new_name="sbc_size",
        )
        drop = manager.preview_sql(
            operation="DROP_COLUMN",
            table_name="wtl_manh_ps",
            old_name="old_depth",
        )
        self.assertEqual(
            add,
            'ALTER TABLE gis."wtl_manh_ps" ADD COLUMN "new_depth" numeric;',
        )
        self.assertEqual(
            rename,
            'ALTER TABLE gis."wtl_manh_ps" RENAME COLUMN "sbc_siz" TO "sbc_size";',
        )
        self.assertEqual(
            drop,
            'ALTER TABLE gis."wtl_manh_ps" DROP COLUMN "old_depth";',
        )
        for sql in (add, rename, drop):
            self.assertIn("ALTER TABLE gis.", sql)
            self.assertNotIn("ctr.", sql)
            self.assertNotIn("hr.", sql)
            self.assertNotIn("prj.", sql)
            self.assertNotIn("ops.", sql)

    def test_visibility_falls_back_to_legacy_visible(self):
        self.assertTrue(manager.effective_form_visible({"visible": True, "form_visible": None}))
        self.assertFalse(manager.effective_form_visible({"visible": False, "form_visible": None}))
        self.assertFalse(manager.effective_form_visible({"visible": True, "form_visible": False}))
        self.assertTrue(manager.effective_table_visible({"visible": False, "table_visible": True}))

    def test_staged_rollout_status_requires_all_registered_tenants(self):
        registered=["a","b"]
        status, complete=manager.rollout_status(
            registered, {"a":"APPLIED"}, ["a"], ["a"]
        )
        self.assertEqual(status,"PARTIAL_APPLIED")
        self.assertFalse(complete)

        status, complete=manager.rollout_status(
            registered, {"a":"APPLIED","b":"APPLIED"}, ["b"], ["b"]
        )
        self.assertEqual(status,"APPLIED")
        self.assertTrue(complete)

        status, complete=manager.rollout_status(
            registered, {"a":"APPLIED","b":"FAILED"}, ["a","b"], ["a"]
        )
        self.assertEqual(status,"PARTIAL_FAILED")
        self.assertFalse(complete)

    def test_admin_schema_ddl_is_gis_only(self):
        cursor = FakeCursor()
        manager.ensure_admin_schema(cursor)
        joined = "\n".join(statement for statement, _ in cursor.statements).lower()
        self.assertIn("gis.definition_layer_group", joined)
        self.assertIn("gis.schema_change", joined)
        self.assertNotIn("alter table ctr.", joined)
        self.assertNotIn("alter table hr.", joined)
        self.assertNotIn("alter table prj.", joined)
        self.assertNotIn("alter table ops.", joined)


ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(os.getenv("GEOFLOW_FORMS_ISOLATED_PG") == "1", "isolated PostgreSQL opt-in only")
class GisSchemaManagerPostgresTests(unittest.TestCase):
    def setUp(self):
        import psycopg2
        self.db = psycopg2.connect(
            host="127.0.0.1", port=55440, dbname="geoflow_forms_test",
            user="geoflow_test", password="geoflow_test",
        )
        self.addCleanup(self.db.close)
        self.addCleanup(self.db.rollback)
        self.cur = self.db.cursor()
        self.addCleanup(self.cur.close)
        self.cur.execute("DROP SCHEMA IF EXISTS gis CASCADE")
        self.cur.execute((ROOT / "docs/architecture/gis-central-definitions.sql").read_text())

    def test_group_layer_field_lifecycle_and_pending_schema_change(self):
        first_group = manager.mutate_admin(
            self.cur,
            {
                "action": "group_admin",
                "group_code": "water",
                "name": "상수",
                "display_name": "상수",
                "sort_order": "1",
                "active": "true",
            },
            actor="test-admin",
        )
        second_group = manager.mutate_admin(
            self.cur,
            {
                "action": "group_admin",
                "group_code": "sewer",
                "name": "하수",
                "display_name": "하수",
                "sort_order": "2",
                "active": "true",
            },
            actor="test-admin",
        )
        layer_id = manager.mutate_admin(
            self.cur,
            {
                "action": "layer_admin",
                "standard_name": "WTL_TEST_PS",
                "physical_name": "wtl_test_ps",
                "label": "테스트 시설",
                "domain_code": "WTL",
                "geometry_kind": "POINT",
                "sort_order": "1",
                "layer_group_id": first_group,
            },
            actor="test-admin",
        )
        self.assertFalse(manager.layer_state(self.cur, layer_id)["active"])
        self.assertEqual(manager.layer_state(self.cur, layer_id)["layer_group_id"], first_group)

        with self.assertRaises(DefinitionError):
            manager.mutate_admin(
                self.cur,
                {"action": "delete_group_admin", "id": first_group},
                actor="test-admin",
            )

        manager.mutate_admin(
            self.cur,
            {
                "action": "bulk_layers_admin",
                "items": json.dumps([{"id": layer_id, "layer_group_id": second_group}]),
            },
            actor="test-admin",
        )
        self.cur.execute(
            "SELECT layer_group_id::text FROM gis.definition_layer WHERE id=%s",
            [layer_id],
        )
        self.assertEqual(self.cur.fetchone()[0], second_group)

        manager.mutate_admin(
            self.cur,
            {"action": "delete_group_admin", "id": first_group},
            actor="test-admin",
        )
        self.assertIsNone(manager.layer_group_state(self.cur, first_group))

        field_id = manager.mutate_admin(
            self.cur,
            {
                "action": "field_admin",
                "source_layer_id": layer_id,
                "physical_name": "new_depth",
                "standard_name": "NEW_DEPTH",
                "label": "추가 심도",
                "storage_data_type": "numeric",
                "kind": "decimal",
                "widget_type": "decimal",
                "form_visible": "true",
                "table_visible": "true",
            },
            actor="test-admin",
        )
        field = manager.field_state(self.cur, field_id)
        self.assertFalse(field["active"])
        self.assertTrue(field["form_visible"])
        self.assertTrue(field["table_visible"])

        change_id = manager.mutate_admin(
            self.cur,
            {
                "action": "schema_change_admin",
                "operation": "ADD_COLUMN",
                "layer_id": layer_id,
                "field_id": field_id,
                "new_name": "new_depth",
                "new_type": "numeric",
            },
            actor="test-admin",
        )
        changes = manager.schema_change_snapshot(self.cur)
        self.assertEqual(changes[0]["id"], change_id)
        self.assertEqual(changes[0]["status"], "PENDING")
        self.assertEqual(
            changes[0]["preview_sql"],
            'ALTER TABLE gis."wtl_test_ps" ADD COLUMN "new_depth" numeric;',
        )
        self.assertGreaterEqual(len(manager.change_log_snapshot(self.cur)), 6)


    def test_physical_add_rename_drop_are_limited_to_gis_schema(self):
        self.cur.execute("CREATE TABLE gis.wtl_test_ps(id uuid PRIMARY KEY)")
        manager.apply_change_to_tenant(
            self.cur,
            {
                "operation": "ADD_COLUMN",
                "table_name": "wtl_test_ps",
                "new_name": "new_depth",
                "new_type": "numeric",
            },
        )
        self.cur.execute(
            """SELECT data_type FROM information_schema.columns
                WHERE table_schema='gis' AND table_name='wtl_test_ps' AND column_name='new_depth'"""
        )
        self.assertEqual(self.cur.fetchone()[0], "numeric")

        manager.apply_change_to_tenant(
            self.cur,
            {
                "operation": "RENAME_COLUMN",
                "table_name": "wtl_test_ps",
                "old_name": "new_depth",
                "new_name": "depth_value",
            },
        )
        self.cur.execute(
            """SELECT count(*) FROM information_schema.columns
                WHERE table_schema='gis' AND table_name='wtl_test_ps' AND column_name='depth_value'"""
        )
        self.assertEqual(self.cur.fetchone()[0], 1)

        manager.apply_change_to_tenant(
            self.cur,
            {
                "operation": "DROP_COLUMN",
                "table_name": "wtl_test_ps",
                "old_name": "depth_value",
            },
        )
        self.cur.execute(
            """SELECT count(*) FROM information_schema.columns
                WHERE table_schema='gis' AND table_name='wtl_test_ps' AND column_name='depth_value'"""
        )
        self.assertEqual(self.cur.fetchone()[0], 0)

        with self.assertRaises(DefinitionError):
            manager.apply_change_to_tenant(
                self.cur,
                {
                    "operation": "ADD_COLUMN",
                    "table_name": "ctr.contracts",
                    "new_name": "forbidden",
                    "new_type": "text",
                },
            )


if __name__ == "__main__":
    unittest.main()
