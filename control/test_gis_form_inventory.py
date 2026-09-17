from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('gis_inventory', ROOT / 'scripts/ops/inspect_gis_form_definition.py')
inventory = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(inventory)


class InventorySafetyTests(unittest.TestCase):
    def test_refuses_writable_connection_before_inspection(self):
        class Cursor:
            def __init__(self): self.queries = []
            def execute(self, query, params=()): self.queries.append(query)
            def fetchone(self): return ('off',)
        cur = Cursor()
        with self.assertRaisesRegex(RuntimeError, 'read_only_required'):
            inventory.inventory(cur)
        self.assertEqual(cur.queries, ['SHOW transaction_read_only'])

    def test_arbitrary_default_literals_are_not_exported(self):
        for value in ["'private@example.test'::text", "nextval('private_sequence'::regclass)", "'secret'::character varying"]:
            self.assertNotIn(value, inventory.default_summary(value))
        for value in [None, 'false', '0', 'now()', 'gen_random_uuid()']:
            self.assertEqual(inventory.default_summary(value), value)

    def test_both_jsonb_driver_modes_are_supported(self):
        value = {'label': '관종', 'widget_type': 'combo'}
        self.assertEqual(inventory.json_object(json.dumps(value)), value)
        self.assertEqual(inventory.json_object(value), value)
        with self.assertRaises(ValueError): inventory.json_object('[]')

    def test_operational_tables_are_not_count_targets(self):
        self.assertTrue({'projects', 'employees', 'users', 'contracts', 'wtl_pipe_lm', 'survey'}.isdisjoint(inventory.METADATA_TABLES))

    def test_remote_shell_parses_and_has_no_deployment_actions(self):
        import subprocess
        import textwrap
        workflow = (ROOT / '.github/workflows/gis-form-inventory.yml').read_text()
        remote = textwrap.dedent(workflow.split("<<'REMOTE'\n", 1)[1].split('          REMOTE\n', 1)[0])
        subprocess.run(['bash', '-n'], input=remote, text=True, check=True)
        self.assertIn('environment: production', workflow)
        for forbidden in ['systemctl restart', 'git checkout', 'git pull', 'manage.py migrate', 'write=True']:
            self.assertNotIn(forbidden, workflow)


@unittest.skipUnless(os.environ.get('GEOFLOW_INVENTORY_ISOLATED_PG') == '1', 'isolated PostgreSQL only')
class InventoryPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import psycopg2
        cls.conn = psycopg2.connect(host='127.0.0.1', port=55441, dbname='geoflow_inventory_test',
                                    user='geoflow_test', password='geoflow_test')
        cls.conn.autocommit = True
        with cls.conn.cursor() as cur:
            cur.execute('SELECT current_database()')
            assert cur.fetchone()[0] == 'geoflow_inventory_test'
            cur.execute('CREATE SCHEMA gis')
            cur.execute('CREATE SCHEMA catalog')
            cur.execute('CREATE TABLE catalog.category_node(id uuid PRIMARY KEY,code text,name text,level integer,active boolean)')
            cur.execute("INSERT INTO catalog.category_node VALUES ('00000000-0000-0000-0000-000000000001','WATER','상수도',2,true)")
            cur.execute((ROOT / 'docs/architecture/gis-central-definitions.sql').read_text().replace('CREATE SCHEMA IF NOT EXISTS gis;', ''))
            cur.execute("INSERT INTO gis.definition_layer VALUES ('WTL_PIPE_LM','상수관로')")
            cur.execute("INSERT INTO gis.definition_field(id,label,kind,source_layer,physical_name) VALUES ('00000000-0000-0000-0000-000000000002','관종','text','WTL_PIPE_LM','saa_cde')")
            cur.execute("CREATE TABLE gis.project_definition(project_id uuid,group_id uuid,additions jsonb,private_items jsonb)")
            cur.execute("INSERT INTO gis.project_definition VALUES ('11111111-2222-3333-4444-555555555555',null,'{}','{\"private label\":\"private value\"}')")
            cur.execute("CREATE TABLE gis.wtl_pipe_lm(id integer,description text DEFAULT 'private-default')")
            cur.execute("INSERT INTO gis.wtl_pipe_lm VALUES (1,'private-feature-data')")
        cls.conn.autocommit = False
        cls.conn.set_session(readonly=True)

    @classmethod
    def tearDownClass(cls):
        cls.conn.rollback()
        cls.conn.close()

    def tearDown(self):
        self.conn.rollback()

    def test_real_schema_and_aggregates_without_operational_values(self):
        with self.conn.cursor() as cur:
            result = inventory.inventory(cur)
        output = json.dumps(result)
        self.assertTrue(result['read_only'])
        self.assertEqual(result['metadata_counts']['definition_field'], 1)
        self.assertEqual(result['central_standard_fields'][0]['label'], '관종')
        self.assertEqual(result['project_configuration_counts'][0]['with_private_items'], 1)
        for forbidden in ['11111111-2222-3333-4444-555555555555', 'private label', 'private value', 'private-feature-data', 'private-default']:
            self.assertNotIn(forbidden, output)
        self.assertNotIn('wtl_pipe_lm', result['metadata_counts'])

    def test_postgres_rejects_mutation(self):
        import psycopg2
        with self.conn.cursor() as cur:
            inventory.inventory(cur)
            with self.assertRaises(psycopg2.errors.ReadOnlySqlTransaction):
                cur.execute("DELETE FROM gis.definition_field")


if __name__ == '__main__':
    unittest.main()
