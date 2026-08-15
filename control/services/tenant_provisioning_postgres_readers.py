from __future__ import annotations

from typing import Protocol


class ReadOnlyPostgresConnector(Protocol):
    """Connection factory that guarantees a read-only PostgreSQL session."""

    read_only: bool

    def __call__(self, *, host: str, port: int): ...


class PostgresReadOnlyDatabaseCatalog:
    """Read PostgreSQL catalog metadata without holding database credentials.

    The connector is injected and must explicitly advertise ``read_only=True``.
    Each returned connection is independently verified with
    ``SHOW transaction_read_only`` before any catalog lookup. The adapter issues
    only parameterized metadata SELECT statements and always closes its cursor
    and connection. It contains no DDL/DML, credential discovery, or production
    connection constructor.
    """

    def __init__(self, connector: ReadOnlyPostgresConnector):
        if connector is None:
            raise ValueError("postgres_connector_required")
        self._connector = connector

    @property
    def read_only(self) -> bool:
        return bool(getattr(self._connector, "read_only", False)) is True

    def _require_read_only_connector(self) -> None:
        if not self.read_only:
            raise RuntimeError("read_only_postgres_connector_required")

    @staticmethod
    def _target(host: str, port: int) -> tuple[str, int]:
        exact_host = str(host or "").strip()
        try:
            exact_port = int(port)
        except (TypeError, ValueError):
            exact_port = 0
        if not exact_host:
            raise ValueError("postgres_host_required")
        if exact_port < 1 or exact_port > 65535:
            raise ValueError("postgres_port_invalid")
        return exact_host, exact_port

    def _catalog_entry_exists(
        self,
        *,
        host: str,
        port: int,
        statement: str,
        identifier: str,
    ) -> bool:
        self._require_read_only_connector()
        exact_host, exact_port = self._target(host, port)
        exact_identifier = str(identifier or "").strip()
        if not exact_identifier:
            raise ValueError("postgres_identifier_required")

        connection = self._connector(host=exact_host, port=exact_port)
        cursor = None
        try:
            cursor = connection.cursor()
            cursor.execute("SHOW transaction_read_only")
            row = cursor.fetchone()
            mode = str(row[0]).strip().lower() if row else ""
            if mode not in {"on", "true", "1"}:
                raise RuntimeError("postgres_read_only_session_required")

            cursor.execute(statement, [exact_identifier])
            return cursor.fetchone() is not None
        finally:
            if cursor is not None:
                cursor.close()
            connection.close()

    def database_exists(self, *, host: str, port: int, database: str) -> bool:
        return self._catalog_entry_exists(
            host=host,
            port=port,
            statement="SELECT 1 FROM pg_database WHERE datname=%s LIMIT 1",
            identifier=database,
        )

    def role_exists(self, *, host: str, port: int, role: str) -> bool:
        return self._catalog_entry_exists(
            host=host,
            port=port,
            statement="SELECT 1 FROM pg_roles WHERE rolname=%s LIMIT 1",
            identifier=role,
        )
