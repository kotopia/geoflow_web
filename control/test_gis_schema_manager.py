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
        self.assertEqual(manager.data_type("varchar(100)"), "varchar(100)")
        self.assertEqual(manager.data_type("character varying(50)"), "varchar(50)")
        self.assertEqual(manager.data_type("numeric(10,2)"), "numeric(10,2)")
        self.assertEqual(manager.storage_type(db_type="varchar", max_length="255"), "varchar(255)")
        self.assertEqual(manager.storage_type(db_type="numeric", precision="8", scale="3"), "numeric(8,3)")
        for value in ("geometry", "serial", "text; drop table x", "varchar(0)", "numeric(2,3)", "public.text"):
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
            registered, {"a":"APPLIED","b":"FAILED"}, ["b"], []
        )
        self.assertEqual(status,"PARTIAL_FAILED")
        self.assertFalse(complete)

        status, complete=manager.rollout_status(
            registered, {"a":"APPLIED","b":"APPLIED"}, ["b"], ["b"]
        )
        self.assertEqual(status,"APPLIED")
        self.assertTrue(complete)

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
        self.cur.execute("DROP SCHEMA IF EXISTS gis CASCADE; DROP SCHEMA IF EXISTS catalog CASCADE")
        self.cur.execute("""CREATE SCHEMA catalog;
            CREATE TABLE catalog.category_node(
              id uuid PRIMARY KEY,code text,name text,level smallint,ord integer,active boolean
            )""")
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
        with self.assertRaises(DefinitionError):
            manager.mutate_admin(
                self.cur,
                {
                    "action": "schema_change_admin",
                    "operation": "ADD_COLUMN",
                    "layer_id": layer_id,
                    "field_id": field_id,
                    "new_name": "different_name",
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


    def test_catalog_layer_many_to_many_and_physical_field_request_flow(self):
        water, sewer = str(uuid4()), str(uuid4())
        self.cur.execute(
            """INSERT INTO catalog.category_node(id,code,name,level,ord,active)
               VALUES (%s,'WATER','상수도',2,1,true),(%s,'SEWER','하수도',2,2,true)""",
            [water, sewer],
        )
        layer_id = manager.mutate_admin(
            self.cur,
            {
                "action": "layer_admin",
                "standard_name": "SURVEY_TEST",
                "physical_name": "survey_test",
                "label": "공용 측량",
                "geometry_kind": "POINT",
                "catalog_ids": json.dumps([water, sewer]),
                "active": "true",
            },
            actor="test-admin",
        )
        self.cur.execute(
            """SELECT catalog_item_id::text FROM gis.definition_layer_catalog
               WHERE layer_id=%s AND catalog_level=2 ORDER BY catalog_item_id""",
            [layer_id],
        )
        self.assertEqual(set(row[0] for row in self.cur.fetchall()), {water, sewer})

        field_id = manager.mutate_admin(
            self.cur,
            {
                "action": "physical_field_create_admin",
                "source_layer_id": layer_id,
                "physical_name": "depth_value",
                "standard_name": "DEPTH_VALUE",
                "label": "깊이",
                "storage_data_type": "numeric",
                "precision": "10",
                "scale": "2",
                "kind": "decimal",
                "widget_type": "decimal",
                "form_visible": "true",
                "table_visible": "true",
            },
            actor="test-admin",
        )
        field = manager.field_state(self.cur, field_id)
        self.assertEqual(field["storage_data_type"], "numeric(10,2)")
        self.assertEqual((field["precision"], field["scale"]), (10, 2))
        self.assertFalse(field["active"])
        changes = manager.schema_change_snapshot(self.cur)
        add = next(x for x in changes if x["field_id"] == field_id)
        self.assertEqual(add["operation"], "ADD_COLUMN")
        self.assertIn("numeric(10,2)", add["preview_sql"])

        manager.mutate_admin(
            self.cur,
            {
                "action": "physical_field_update_admin",
                "id": field_id,
                "physical_name": "depth_m",
                "label": "깊이(m)",
                "storage_data_type": "numeric",
                "precision": "10",
                "scale": "2",
                "kind": "decimal",
                "widget_type": "decimal",
            },
            actor="test-admin",
        )
        renamed = [x for x in manager.schema_change_snapshot(self.cur) if x["field_id"] == field_id and x["operation"] == "RENAME_COLUMN"]
        self.assertEqual(len(renamed), 1)
        self.assertEqual(manager.field_state(self.cur, field_id)["physical_name"], "depth_value")

        other_field_id = manager.mutate_admin(
            self.cur,
            {
                "action": "physical_field_create_admin",
                "source_layer_id": layer_id,
                "physical_name": "other_value",
                "standard_name": "OTHER_VALUE",
                "label": "다른 필드",
                "storage_data_type": "integer",
                "kind": "integer",
                "widget_type": "integer",
            },
            actor="test-admin",
        )
        self.cur.execute(
            "UPDATE gis.definition_field SET active=true WHERE id=%s",
            [other_field_id],
        )

        manager.mutate_admin(
            self.cur,
            {"action": "physical_field_delete_admin", "id": field_id},
            actor="test-admin",
        )
        self.assertFalse(manager.field_state(self.cur, field_id)["active"])
        self.assertTrue(manager.field_state(self.cur, other_field_id)["active"])
        dropped = [x for x in manager.schema_change_snapshot(self.cur) if x["field_id"] == field_id and x["operation"] == "DROP_COLUMN"]
        self.assertEqual(len(dropped), 1)
        other_dropped = [x for x in manager.schema_change_snapshot(self.cur) if x["field_id"] == other_field_id and x["operation"] == "DROP_COLUMN"]
        self.assertEqual(other_dropped, [])


    def test_rename_request_reuse_conflict_and_tenant_data_preservation(self):
        water = str(uuid4())
        self.cur.execute(
            "INSERT INTO catalog.category_node(id,code,name,level,ord,active) VALUES (%s,'WATER','상수도',2,1,true)",
            [water],
        )
        layer_id = manager.mutate_admin(
            self.cur,
            {
                "action": "layer_admin",
                "standard_name": "WTL_RENAME_PS",
                "physical_name": "wtl_rename_ps",
                "label": "Rename 테스트",
                "geometry_kind": "POINT",
                "catalog_ids": json.dumps([water]),
                "active": "true",
            },
            actor="test-admin",
        )
        field_id = str(uuid4())
        self.cur.execute(
            """INSERT INTO gis.definition_field(
                 id,source_layer_id,physical_name,standard_name,label,storage_data_type,
                 storage_udt_name,kind,widget_type,active)
               VALUES (%s,%s,'gid','GID','GID','bigint','int8','integer','integer',true)""",
            [field_id, layer_id],
        )

        first, created = manager.ensure_rename_change(
            self.cur, field_id=field_id, layer_id=layer_id,
            old_name="gid", new_name="gid_test", actor="test-admin",
        )
        self.assertTrue(created)
        second, created = manager.ensure_rename_change(
            self.cur, field_id=field_id, layer_id=layer_id,
            old_name="gid", new_name="gid_test", actor="test-admin",
        )
        self.assertEqual(second, first)
        self.assertFalse(created)
        with self.assertRaisesRegex(DefinitionError, "미완료 물리 필드명 변경 요청"):
            manager.ensure_rename_change(
                self.cur, field_id=field_id, layer_id=layer_id,
                old_name="gid", new_name="gid_other", actor="test-admin",
            )
        self.cur.execute(
            """SELECT count(*) FROM gis.schema_change
               WHERE field_id=%s AND operation='RENAME_COLUMN'""",
            [field_id],
        )
        self.assertEqual(self.cur.fetchone()[0], 1)
        self.assertEqual(manager.field_state(self.cur, field_id)["physical_name"], "gid")

        import psycopg2
        suffix = uuid4().hex[:10]
        tenant_names = [f"geoflow_tenant_a_{suffix}", f"geoflow_tenant_b_{suffix}"]
        admin = psycopg2.connect(
            host="127.0.0.1", port=55440, dbname="postgres",
            user="geoflow_test", password="geoflow_test",
        )
        admin.autocommit = True
        self.addCleanup(admin.close)
        for dbname in tenant_names:
            admin.cursor().execute(f'CREATE DATABASE "{dbname}"')
            self.addCleanup(lambda name=dbname: admin.cursor().execute(
                f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'
            ))
        change = {
            "operation": "RENAME_COLUMN",
            "table_name": "wtl_rename_ps",
            "old_name": "gid",
            "new_name": "gid_test",
        }
        for index, dbname in enumerate(tenant_names, start=1):
            db = psycopg2.connect(
                host="127.0.0.1", port=55440, dbname=dbname,
                user="geoflow_test", password="geoflow_test",
            )
            self.addCleanup(db.close)
            cur = db.cursor()
            cur.execute("CREATE SCHEMA gis")
            cur.execute("CREATE TABLE gis.wtl_rename_ps(gid bigint, label text)")
            cur.execute(
                "INSERT INTO gis.wtl_rename_ps(gid,label) VALUES (%s,%s)",
                [index, f"row-{index}"],
            )
            manager.apply_change_to_tenant(cur, change)
            db.commit()
            cur.execute(
                """SELECT count(*) FROM information_schema.columns
                   WHERE table_schema='gis' AND table_name='wtl_rename_ps' AND column_name='gid'"""
            )
            self.assertEqual(cur.fetchone()[0], 0)
            cur.execute(
                """SELECT count(*) FROM information_schema.columns
                   WHERE table_schema='gis' AND table_name='wtl_rename_ps' AND column_name='gid_test'"""
            )
            self.assertEqual(cur.fetchone()[0], 1)
            cur.execute("SELECT gid_test,label FROM gis.wtl_rename_ps")
            self.assertEqual(cur.fetchone(), (index, f"row-{index}"))
            self.assertTrue(manager.change_already_applied(cur, change))

        # Tenant DDL alone must never move the central Source of Truth.
        self.assertEqual(manager.field_state(self.cur, field_id)["physical_name"], "gid")

    def test_name_and_type_change_message_is_explicit(self):
        water = str(uuid4())
        self.cur.execute(
            "INSERT INTO catalog.category_node(id,code,name,level,ord,active) VALUES (%s,'WATER','상수도',2,1,true)",
            [water],
        )
        layer_id = manager.mutate_admin(
            self.cur,
            {
                "action": "layer_admin",
                "standard_name": "WTL_BOTH_PS",
                "physical_name": "wtl_both_ps",
                "label": "동시변경 테스트",
                "geometry_kind": "POINT",
                "catalog_ids": json.dumps([water]),
            },
            actor="test-admin",
        )
        field_id = str(uuid4())
        self.cur.execute(
            """INSERT INTO gis.definition_field(
                 id,source_layer_id,physical_name,standard_name,label,storage_data_type,
                 storage_udt_name,kind,widget_type,active)
               VALUES (%s,%s,'gid','GID','GID','bigint','int8','integer','integer',true)""",
            [field_id, layer_id],
        )
        with self.assertRaisesRegex(
            DefinitionError,
            "물리 필드명과 DB 타입은 동시에 변경할 수 없습니다",
        ):
            manager.mutate_admin(
                self.cur,
                {
                    "action": "physical_field_update_admin",
                    "id": field_id,
                    "physical_name": "gid_test",
                    "label": "GID",
                    "storage_data_type": "integer",
                    "kind": "integer",
                    "widget_type": "integer",
                },
                actor="test-admin",
            )


    def test_add_column_applies_dimensions_default_and_nullability(self):
        self.cur.execute("CREATE TABLE gis.wtl_dimension_ps(id uuid PRIMARY KEY)")
        manager.apply_change_to_tenant(
            self.cur,
            {
                "operation": "ADD_COLUMN",
                "table_name": "wtl_dimension_ps",
                "new_name": "depth_value",
                "new_type": "numeric(8,3)",
                "field_nullable": False,
                "field_default": "0",
            },
        )
        state = manager.tenant_column_state(
            self.cur, table_name="wtl_dimension_ps", column_name="depth_value"
        )
        self.assertEqual(manager._canonical_db_type(state["column"]), "numeric(8,3)")
        self.assertEqual(state["column"]["is_nullable"], "NO")

    def test_existing_varchar_dimensions_do_not_create_spurious_type_change(self):
        water = str(uuid4())
        self.cur.execute(
            "INSERT INTO catalog.category_node(id,code,name,level,ord,active) VALUES (%s,'WATER','상수도',2,1,true)",
            [water],
        )
        layer_id = manager.mutate_admin(
            self.cur,
            {
                "action": "layer_admin",
                "standard_name": "WTL_TEXT_PS",
                "physical_name": "wtl_text_ps",
                "label": "문자 테스트",
                "geometry_kind": "POINT",
                "catalog_ids": json.dumps([water]),
            },
            actor="test-admin",
        )
        field_id = str(uuid4())
        self.cur.execute(
            """INSERT INTO gis.definition_field(
                 id,source_layer_id,physical_name,standard_name,label,storage_data_type,
                 storage_udt_name,max_length,kind,widget_type,active)
               VALUES (%s,%s,'memo','MEMO','메모','character varying','varchar',50,'text','text',true)""",
            [field_id, layer_id],
        )
        manager.mutate_admin(
            self.cur,
            {
                "action": "physical_field_update_admin",
                "id": field_id,
                "physical_name": "memo",
                "label": "메모 수정",
                "storage_data_type": "varchar",
                "max_length": "50",
                "kind": "text",
                "widget_type": "text",
            },
            actor="test-admin",
        )
        changes = [
            x for x in manager.schema_change_snapshot(self.cur)
            if x["field_id"] == field_id and x["operation"] == "ALTER_TYPE"
        ]
        self.assertEqual(changes, [])


    def test_safe_alter_type_conversions_and_dimensions(self):
        self.cur.execute("""CREATE TABLE gis.type_change_ps(
            n numeric(10,2),
            i integer,
            txt varchar(20),
            n2 numeric(10,2)
        )""")
        self.cur.execute(
            "INSERT INTO gis.type_change_ps(n,i,txt,n2) VALUES (12.00,7,'abcdef',3.25)"
        )

        manager.apply_change_to_tenant(
            self.cur,
            {
                "operation": "ALTER_TYPE",
                "table_name": "type_change_ps",
                "old_name": "n",
                "new_type": "integer",
            },
        )
        manager.apply_change_to_tenant(
            self.cur,
            {
                "operation": "ALTER_TYPE",
                "table_name": "type_change_ps",
                "old_name": "i",
                "new_type": "numeric(10,2)",
            },
        )
        manager.apply_change_to_tenant(
            self.cur,
            {
                "operation": "ALTER_TYPE",
                "table_name": "type_change_ps",
                "old_name": "txt",
                "new_type": "varchar(50)",
            },
        )
        manager.apply_change_to_tenant(
            self.cur,
            {
                "operation": "ALTER_TYPE",
                "table_name": "type_change_ps",
                "old_name": "n2",
                "new_type": "numeric(12,3)",
            },
        )

        states = {}
        for name in ("n", "i", "txt", "n2"):
            states[name] = manager.tenant_column_state(
                self.cur, table_name="type_change_ps", column_name=name
            )["column"]
        self.assertEqual(manager._canonical_db_type(states["n"]), "integer")
        self.assertEqual(manager._canonical_db_type(states["i"]), "numeric(10,2)")
        self.assertEqual(manager._canonical_db_type(states["txt"]), "varchar(50)")
        self.assertEqual(manager._canonical_db_type(states["n2"]), "numeric(12,3)")

        self.cur.execute("SELECT n,i,txt,n2 FROM gis.type_change_ps")
        row = self.cur.fetchone()
        self.assertEqual(row[0], 12)
        self.assertEqual(str(row[1]), "7.00")
        self.assertEqual(row[2], "abcdef")
        self.assertEqual(str(row[3]), "3.250")

    def test_varchar_shrink_never_truncates_existing_values(self):
        self.cur.execute("CREATE TABLE gis.text_change_ps(v varchar(20))")
        self.cur.execute("INSERT INTO gis.text_change_ps(v) VALUES ('1234567890')")
        with self.assertRaisesRegex(DefinitionError, "길이를 초과하는 값"):
            manager.apply_change_to_tenant(
                self.cur,
                {
                    "operation": "ALTER_TYPE",
                    "table_name": "text_change_ps",
                    "old_name": "v",
                    "new_type": "varchar(5)",
                },
            )
        state = manager.tenant_column_state(
            self.cur, table_name="text_change_ps", column_name="v"
        )["column"]
        self.assertEqual(manager._canonical_db_type(state), "varchar(20)")
        self.cur.execute("SELECT v FROM gis.text_change_ps")
        self.assertEqual(self.cur.fetchone()[0], "1234567890")

    def test_unsupported_automatic_type_conversion_is_blocked(self):
        self.cur.execute("CREATE TABLE gis.unsupported_type_ps(v text)")
        with self.assertRaisesRegex(DefinitionError, "자동 변환을 지원하지 않는"):
            manager.apply_change_to_tenant(
                self.cur,
                {
                    "operation": "ALTER_TYPE",
                    "table_name": "unsupported_type_ps",
                    "old_name": "v",
                    "new_type": "integer",
                },
            )

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
        self.assertTrue(manager.change_already_applied(
            self.cur, {"operation":"ADD_COLUMN","table_name":"wtl_test_ps",
                       "new_name":"new_depth","new_type":"numeric"}
        ))

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
        self.assertTrue(manager.change_already_applied(
            self.cur, {"operation":"RENAME_COLUMN","table_name":"wtl_test_ps",
                       "old_name":"new_depth","new_name":"depth_value"}
        ))

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
        self.assertTrue(manager.change_already_applied(
            self.cur, {"operation":"DROP_COLUMN","table_name":"wtl_test_ps",
                       "old_name":"depth_value"}
        ))

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
