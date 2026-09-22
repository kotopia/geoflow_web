import unittest

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

    def test_admin_schema_ddl_is_gis_only(self):
        cursor = FakeCursor()
        manager.ensure_admin_schema(cursor)
        joined = "\n".join(statement for statement, _ in cursor.statements).lower()
        self.assertIn("gis.definition_group", joined)
        self.assertIn("gis.schema_change", joined)
        self.assertNotIn("alter table ctr.", joined)
        self.assertNotIn("alter table hr.", joined)
        self.assertNotIn("alter table prj.", joined)
        self.assertNotIn("alter table ops.", joined)


if __name__ == "__main__":
    unittest.main()
