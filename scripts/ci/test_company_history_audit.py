import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest

path = Path(__file__).resolve().parents[1] / 'ops/audit_company_migration_history.py'
spec = importlib.util.spec_from_file_location('audit', path)
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)

class HistoryTests(unittest.TestCase):
    def graph(self):
        return SimpleNamespace(node_map={('app','first'):SimpleNamespace(parents=[]),
            ('app','second'):SimpleNamespace(parents=[SimpleNamespace(key=('app','first'))])})

    def test_exact_missing_predecessor(self):
        self.assertEqual(audit.missing_dependencies(self.graph(), {('app','second')}, {}),
                         [(('app','second'),('app','first'))])

    def test_consistent_and_unknown_rows_not_exposed(self):
        self.assertEqual(audit.missing_dependencies(self.graph(),
            {('app','first'),('app','second'),('private','unknown')}, {}), [])

    def test_complete_squash_replacement(self):
        replacements={('app','first'): SimpleNamespace(replaces=[('app','old')])}
        self.assertEqual(audit.missing_dependencies(self.graph(),
            {('app','second'),('app','old')}, replacements), [])

if __name__ == '__main__':
    unittest.main()
