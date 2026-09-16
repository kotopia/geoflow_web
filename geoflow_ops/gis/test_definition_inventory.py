import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from geoflow_ops.gis.definition_inventory import inspect_definition_storage


ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "definition_inventory_cli", ROOT / "scripts/ops/inspect_gis_definition_storage.py")
cli = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cli)


class Cursor:
    def __init__(self, readonly="on"):
        self.readonly = readonly
        self.statements = []
        self.description = [("example",)]

    def execute(self, sql, params=()):
        self.statements.append((sql, params))

    def fetchone(self):
        return "tenant_test", self.readonly, "PostgreSQL test double"

    def fetchall(self):
        return []


class InventoryTests(unittest.TestCase):
    def test_rejects_write_transaction_before_inventory(self):
        cursor = Cursor("off")
        with self.assertRaises(RuntimeError):
            inspect_definition_storage(cursor)
        self.assertEqual(len(cursor.statements), 1)

    def test_only_catalog_selects_and_no_business_queries(self):
        cursor = Cursor()
        report = inspect_definition_storage(cursor)
        self.assertEqual(report["database"], "tenant_test")
        self.assertTrue(report["read_only"])
        self.assertEqual(len(cursor.statements), 4)
        for sql, _ in cursor.statements:
            self.assertTrue(sql.lstrip().startswith("SELECT"))
            self.assertNotIn("SELECT *", sql)
            self.assertNotIn("pg_get_expr", sql)
            self.assertNotIn("pg_get_functiondef", sql)
        self.assertEqual(cursor.statements[2][1][0], ["gis", "catalog"])

    def test_private_output_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "inventory.json"
            cli.write_private_report(path, {"ok": True})
            self.assertEqual(json.loads(path.read_text()), {"ok": True})
            if os.name == "posix":
                self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            with self.assertRaises(FileExistsError):
                cli.write_private_report(path, {"changed": True})
            self.assertEqual(json.loads(path.read_text()), {"ok": True})

    @unittest.skipUnless(os.name == "posix", "symlink behavior")
    def test_symlink_output_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "inventory.json"
            target = Path(tmp) / "other.json"
            path.symlink_to(target)
            with self.assertRaises(FileExistsError):
                cli.write_private_report(path, {})
            self.assertFalse(target.exists())

    def test_exception_does_not_disclose_secret_or_create_success_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "inventory.json"
            stderr = io.StringIO()
            with patch.object(cli, "collect", side_effect=RuntimeError("password=secret")), contextlib.redirect_stderr(stderr):
                result = cli.main(["--group-code", "example", "--db-alias", "tenant", "--output", str(path)])
            self.assertEqual(result, 2)
            self.assertNotIn("secret", stderr.getvalue())
            self.assertFalse(path.exists())

    def test_central_alias_rejected_before_django_setup(self):
        with self.assertRaises(ValueError):
            cli.collect("example", "default")


if __name__ == "__main__":
    unittest.main()
