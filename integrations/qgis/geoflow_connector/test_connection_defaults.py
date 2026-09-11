from __future__ import annotations

import unittest

from integrations.qgis.geoflow_connector.connection_defaults import (
    PRODUCTION_SERVER_URL,
    migrate_legacy_connection_defaults,
)


class ConnectionDefaultsTests(unittest.TestCase):
    def test_known_development_defaults_are_migrated(self):
        server, email = migrate_legacy_connection_defaults(
            "http://127.0.0.1:8000/",
            "GIS-DEV-ADMIN@GEOFLOW.INVALID",
        )
        self.assertEqual(server, PRODUCTION_SERVER_URL)
        self.assertEqual(email, "")

    def test_user_values_are_preserved(self):
        server, email = migrate_legacy_connection_defaults(
            "https://customer.example.com/",
            "USER@example.com",
        )
        self.assertEqual(server, "https://customer.example.com/")
        self.assertEqual(email, "user@example.com")


if __name__ == "__main__":
    unittest.main()
