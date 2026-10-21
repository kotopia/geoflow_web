import sqlite3
import tempfile
import unittest
from pathlib import Path

from sync.online import (
    change_signature,
    clear_legacy_queue,
    legacy_queue_packages,
    legacy_queue_status,
)


class OnlineOnlySyncTests(unittest.TestCase):
    def test_signature_is_stable_without_persistence(self):
        changes = [{"action": "delete", "layer": "A", "id": "1"}]
        self.assertEqual(change_signature(changes), change_signature(list(changes)))

    def test_legacy_rows_are_read_only_until_explicit_cleanup(self):
        with tempfile.TemporaryDirectory() as folder:
            path = str(Path(folder) / "legacy.gpkg")
            connection = sqlite3.connect(path)
            connection.execute("CREATE TABLE _geoflow_outbox(value TEXT)")
            connection.execute("INSERT INTO _geoflow_outbox(value) VALUES ('old')")
            connection.commit()
            connection.close()
            self.assertEqual(sum(legacy_queue_status(path).values()), 1)
            self.assertEqual(sum(legacy_queue_status(path).values()), 1)
            self.assertEqual(clear_legacy_queue(path), 1)
            self.assertEqual(sum(legacy_queue_status(path).values()), 0)

    def test_migration_scan_includes_quarantined_packages_without_mutation(self):
        with tempfile.TemporaryDirectory() as folder:
            quarantine = Path(folder) / "_recovery_quarantine_old"
            quarantine.mkdir()
            path = quarantine / "legacy.gpkg"
            connection = sqlite3.connect(path)
            connection.execute("CREATE TABLE _geoflow_outbox(value TEXT)")
            connection.execute("INSERT INTO _geoflow_outbox(value) VALUES ('old')")
            connection.commit()
            connection.close()

            found = legacy_queue_packages(folder)
            self.assertEqual([(item[0], sum(item[1].values())) for item in found],
                             [(str(path), 1)])
            self.assertEqual(sum(legacy_queue_status(str(path)).values()), 1)


if __name__ == "__main__":
    unittest.main()
