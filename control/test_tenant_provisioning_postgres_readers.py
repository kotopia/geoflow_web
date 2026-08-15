from django.test import SimpleTestCase

from control.services.tenant_provisioning_postgres_readers import (
    PostgresReadOnlyDatabaseCatalog,
)


class FakeCursor:
    def __init__(
        self,
        ledger,
        *,
        transaction_read_only="on",
        databases=(),
        roles=(),
        fail_on_catalog=False,
    ):
        self.ledger = ledger
        self.transaction_read_only = transaction_read_only
        self.databases = set(databases)
        self.roles = set(roles)
        self.fail_on_catalog = fail_on_catalog
        self.statement = ""
        self.params = None

    def execute(self, statement, params=None):
        self.statement = statement
        self.params = params
        self.ledger.append(("execute", statement, params))
        if self.fail_on_catalog and statement.startswith("SELECT 1 FROM pg_"):
            raise RuntimeError("provider detail must remain private")

    def fetchone(self):
        if self.statement == "SHOW transaction_read_only":
            return (self.transaction_read_only,)
        if "FROM pg_database" in self.statement:
            return (1,) if self.params[0] in self.databases else None
        if "FROM pg_roles" in self.statement:
            return (1,) if self.params[0] in self.roles else None
        raise AssertionError("unexpected statement")

    def close(self):
        self.ledger.append(("cursor_close",))


class FakeConnection:
    def __init__(self, ledger, **cursor_kwargs):
        self.ledger = ledger
        self.cursor_kwargs = cursor_kwargs

    def cursor(self):
        self.ledger.append(("cursor",))
        return FakeCursor(self.ledger, **self.cursor_kwargs)

    def close(self):
        self.ledger.append(("connection_close",))


class FakeReadOnlyConnector:
    read_only = True

    def __init__(self, ledger, **cursor_kwargs):
        self.ledger = ledger
        self.cursor_kwargs = cursor_kwargs

    def __call__(self, *, host, port):
        self.ledger.append(("connect", host, port))
        return FakeConnection(self.ledger, **self.cursor_kwargs)


class PostgresReadOnlyDatabaseCatalogTests(SimpleTestCase):
    def test_database_lookup_verifies_read_only_session_before_select(self):
        ledger = []
        connector = FakeReadOnlyConnector(ledger, databases={"new_tenant_db"})
        catalog = PostgresReadOnlyDatabaseCatalog(connector)

        self.assertTrue(catalog.read_only)
        self.assertTrue(
            catalog.database_exists(
                host="db.internal.example",
                port=5432,
                database="new_tenant_db",
            )
        )
        self.assertEqual(
            ledger,
            [
                ("connect", "db.internal.example", 5432),
                ("cursor",),
                ("execute", "SHOW transaction_read_only", None),
                (
                    "execute",
                    "SELECT 1 FROM pg_database WHERE datname=%s LIMIT 1",
                    ["new_tenant_db"],
                ),
                ("cursor_close",),
                ("connection_close",),
            ],
        )

    def test_role_lookup_is_parameterized_and_returns_definitive_absence(self):
        ledger = []
        connector = FakeReadOnlyConnector(ledger, roles={"another_role"})
        catalog = PostgresReadOnlyDatabaseCatalog(connector)

        self.assertFalse(
            catalog.role_exists(
                host="db.internal.example",
                port="5432",
                role="planned_role",
            )
        )
        self.assertIn(
            (
                "execute",
                "SELECT 1 FROM pg_roles WHERE rolname=%s LIMIT 1",
                ["planned_role"],
            ),
            ledger,
        )

    def test_unmarked_connector_is_rejected_before_connection(self):
        ledger = []
        connector = FakeReadOnlyConnector(ledger)
        connector.read_only = False
        catalog = PostgresReadOnlyDatabaseCatalog(connector)

        self.assertFalse(catalog.read_only)
        with self.assertRaisesMessage(
            RuntimeError,
            "read_only_postgres_connector_required",
        ):
            catalog.database_exists(
                host="db.internal.example",
                port=5432,
                database="planned_db",
            )

        self.assertEqual(ledger, [])

    def test_session_not_actually_read_only_fails_before_catalog_select(self):
        ledger = []
        connector = FakeReadOnlyConnector(ledger, transaction_read_only="off")
        catalog = PostgresReadOnlyDatabaseCatalog(connector)

        with self.assertRaisesMessage(
            RuntimeError,
            "postgres_read_only_session_required",
        ):
            catalog.database_exists(
                host="db.internal.example",
                port=5432,
                database="planned_db",
            )

        executed = [entry for entry in ledger if entry[0] == "execute"]
        self.assertEqual(executed, [("execute", "SHOW transaction_read_only", None)])
        self.assertEqual(ledger[-2:], [("cursor_close",), ("connection_close",)])

    def test_catalog_failure_propagates_and_still_closes_resources(self):
        ledger = []
        connector = FakeReadOnlyConnector(ledger, fail_on_catalog=True)
        catalog = PostgresReadOnlyDatabaseCatalog(connector)

        with self.assertRaisesRegex(RuntimeError, "provider detail"):
            catalog.role_exists(
                host="db.internal.example",
                port=5432,
                role="planned_role",
            )

        self.assertEqual(ledger[-2:], [("cursor_close",), ("connection_close",)])

    def test_invalid_target_is_rejected_before_connection(self):
        ledger = []
        catalog = PostgresReadOnlyDatabaseCatalog(FakeReadOnlyConnector(ledger))

        with self.assertRaisesMessage(ValueError, "postgres_host_required"):
            catalog.database_exists(host="", port=5432, database="planned_db")
        with self.assertRaisesMessage(ValueError, "postgres_port_invalid"):
            catalog.database_exists(
                host="db.internal.example",
                port=0,
                database="planned_db",
            )
        with self.assertRaisesMessage(ValueError, "postgres_identifier_required"):
            catalog.database_exists(
                host="db.internal.example",
                port=5432,
                database="",
            )

        self.assertEqual(ledger, [])

    def test_connector_is_injected_and_required(self):
        with self.assertRaisesMessage(ValueError, "postgres_connector_required"):
            PostgresReadOnlyDatabaseCatalog(None)
