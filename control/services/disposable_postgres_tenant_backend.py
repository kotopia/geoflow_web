from __future__ import annotations

import hashlib
import os
import secrets
import uuid
from contextlib import contextmanager
from dataclasses import dataclass

import psycopg2
from psycopg2 import sql
from django.conf import settings
from django.core.management import call_command
from django.db import connections

from control.services.tenant_provisioning_contract import TenantProvisioningPlan
from control.tenant_migration_context import allow_tenant_provisioning_migrations


class DisposableTenantBackendError(RuntimeError):
    """Non-secret failure code for the disposable provisioning rehearsal backend."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class DisposablePostgresConfig:
    host: str
    port: int
    admin_database: str
    admin_user: str
    admin_password: str
    sslmode: str = "disable"


class DisposablePostgresTenantBackend:
    """CI-only Postgres backend for rehearsing tenant DB lifecycle.

    This backend intentionally refuses non-local hosts and non-GitHub-Actions
    execution. It never creates AWS secrets, changes IAM, publishes GroupDBConfig,
    or touches production resources. A separate reviewed production backend is
    required later.
    """

    MARKER_PREFIX = "geoflow:disposable-tenant:"

    def __init__(self, config: DisposablePostgresConfig):
        if os.environ.get("GITHUB_ACTIONS") != "true":
            raise DisposableTenantBackendError("github_actions_required")
        if str(config.host).strip().lower() not in {"127.0.0.1", "localhost"}:
            raise DisposableTenantBackendError("local_postgres_required")
        if not str(config.admin_database or "").strip():
            raise DisposableTenantBackendError("admin_database_required")
        if not str(config.admin_user or "").strip():
            raise DisposableTenantBackendError("admin_user_required")
        if not str(config.admin_password or ""):
            raise DisposableTenantBackendError("admin_password_required")
        if int(config.port) < 1 or int(config.port) > 65535:
            raise DisposableTenantBackendError("admin_port_invalid")

        self.config = config
        self._database_password = secrets.token_urlsafe(48)
        self._lock_connection = None

    def _marker(self, plan: TenantProvisioningPlan) -> str:
        try:
            group_id = str(uuid.UUID(str(plan.group_id)))
        except (TypeError, ValueError, AttributeError):
            raise DisposableTenantBackendError("group_id_invalid") from None
        return self.MARKER_PREFIX + group_id

    def _admin_connect(self, *, database: str | None = None):
        connection = psycopg2.connect(
            dbname=database or self.config.admin_database,
            user=self.config.admin_user,
            password=self.config.admin_password,
            host=self.config.host,
            port=self.config.port,
            sslmode=self.config.sslmode,
            connect_timeout=8,
        )
        connection.autocommit = True
        return connection

    def _operation_connection(self):
        if self._lock_connection is None or self._lock_connection.closed:
            raise DisposableTenantBackendError("provisioning_lock_required")
        return self._lock_connection

    @staticmethod
    def _advisory_key(group_id: str) -> int:
        digest = hashlib.sha256(group_id.encode("utf-8")).digest()[:8]
        return int.from_bytes(digest, byteorder="big", signed=True)

    @contextmanager
    def lock(self, plan: TenantProvisioningPlan):
        if self._lock_connection is not None:
            raise DisposableTenantBackendError("provisioning_lock_already_held")
        connection = self._admin_connect()
        key = self._advisory_key(str(plan.group_id))
        acquired = False
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT pg_try_advisory_lock(%s)", [key])
                row = cursor.fetchone()
                acquired = bool(row and row[0] is True)
            if not acquired:
                raise DisposableTenantBackendError("provisioning_lock_unavailable")
            self._lock_connection = connection
            yield
        finally:
            if acquired and not connection.closed:
                try:
                    with connection.cursor() as cursor:
                        cursor.execute("SELECT pg_advisory_unlock(%s)", [key])
                except Exception:
                    pass
            self._lock_connection = None
            connection.close()

    def _role_marker(self, role_name: str) -> str | None:
        connection = self._operation_connection()
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT shobj_description(oid, 'pg_authid')
                  FROM pg_roles
                 WHERE rolname=%s
                """,
                [role_name],
            )
            row = cursor.fetchone()
        return str(row[0]) if row and row[0] is not None else None

    def _database_marker(self, database_name: str) -> str | None:
        connection = self._operation_connection()
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT shobj_description(oid, 'pg_database')
                  FROM pg_database
                 WHERE datname=%s
                """,
                [database_name],
            )
            row = cursor.fetchone()
        return str(row[0]) if row and row[0] is not None else None

    def ensure_database_role(self, plan: TenantProvisioningPlan) -> bool:
        connection = self._operation_connection()
        marker = self._marker(plan)
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1 FROM pg_roles WHERE rolname=%s", [plan.db_user])
            exists = cursor.fetchone() is not None
            if exists:
                existing_marker = self._role_marker(plan.db_user)
                if existing_marker == marker:
                    raise DisposableTenantBackendError(
                        "rehearsal_role_left_from_prior_attempt"
                    )
                raise DisposableTenantBackendError("database_role_name_conflict")

            cursor.execute(
                sql.SQL("CREATE ROLE {} LOGIN PASSWORD {}").format(
                    sql.Identifier(plan.db_user),
                    sql.Literal(self._database_password),
                )
            )
            cursor.execute(
                sql.SQL("COMMENT ON ROLE {} IS {}").format(
                    sql.Identifier(plan.db_user),
                    sql.Literal(marker),
                )
            )
        return True

    def ensure_database(self, plan: TenantProvisioningPlan) -> bool:
        connection = self._operation_connection()
        marker = self._marker(plan)
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT 1 FROM pg_database WHERE datname=%s",
                [plan.db_name],
            )
            exists = cursor.fetchone() is not None
            if exists:
                existing_marker = self._database_marker(plan.db_name)
                if existing_marker == marker:
                    raise DisposableTenantBackendError(
                        "rehearsal_database_left_from_prior_attempt"
                    )
                raise DisposableTenantBackendError("database_name_conflict")

            cursor.execute(
                sql.SQL("CREATE DATABASE {} OWNER {}").format(
                    sql.Identifier(plan.db_name),
                    sql.Identifier(plan.db_user),
                )
            )
            cursor.execute(
                sql.SQL("COMMENT ON DATABASE {} IS {}").format(
                    sql.Identifier(plan.db_name),
                    sql.Literal(marker),
                )
            )
        return True

    def enable_postgis(self, plan: TenantProvisioningPlan) -> None:
        connection = self._admin_connect(database=plan.db_name)
        try:
            with connection.cursor() as cursor:
                cursor.execute("CREATE EXTENSION IF NOT EXISTS postgis")
                cursor.execute(
                    "SELECT 1 FROM pg_extension WHERE extname='postgis'"
                )
                if cursor.fetchone() != (1,):
                    raise DisposableTenantBackendError("postgis_extension_unavailable")
        finally:
            connection.close()

    @contextmanager
    def _registered_django_alias(self, plan: TenantProvisioningPlan):
        alias = str(plan.db_alias).strip()
        central_alias = getattr(settings, "CENTRAL_DB_ALIAS", "default")
        if alias == central_alias:
            raise DisposableTenantBackendError("central_alias_forbidden")
        if alias in connections.settings:
            raise DisposableTenantBackendError("dynamic_alias_already_registered")

        config = {
            "ENGINE": "django.contrib.gis.db.backends.postgis",
            "NAME": plan.db_name,
            "USER": plan.db_user,
            "PASSWORD": self._database_password,
            "HOST": self.config.host,
            "PORT": str(self.config.port),
            "OPTIONS": {"sslmode": self.config.sslmode},
            "ATOMIC_REQUESTS": False,
            "CONN_MAX_AGE": 0,
            "CONN_HEALTH_CHECKS": False,
            "AUTOCOMMIT": True,
            "TIME_ZONE": None,
            "TEST": {},
        }

        settings_registry = settings.DATABASES
        active_registry = connections.settings
        active_registry[alias] = config
        if settings_registry is not active_registry:
            settings_registry[alias] = config
        try:
            yield alias
        finally:
            try:
                connections[alias].close()
            except Exception:
                pass
            active_registry.pop(alias, None)
            if settings_registry is not active_registry:
                settings_registry.pop(alias, None)
            try:
                del connections[alias]
            except Exception:
                pass

    def apply_tenant_schema(self, plan: TenantProvisioningPlan) -> None:
        self._operation_connection()
        with self._registered_django_alias(plan) as alias:
            with allow_tenant_provisioning_migrations(alias):
                call_command(
                    "migrate",
                    database=alias,
                    interactive=False,
                    verbosity=0,
                )
                call_command(
                    "migrate",
                    database=alias,
                    check=True,
                    interactive=False,
                    verbosity=0,
                )

    def verify_database_schema(self, plan: TenantProvisioningPlan) -> None:
        connection = psycopg2.connect(
            dbname=plan.db_name,
            user=plan.db_user,
            password=self._database_password,
            host=self.config.host,
            port=self.config.port,
            sslmode=self.config.sslmode,
            connect_timeout=8,
        )
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
                if cursor.fetchone() != (1,):
                    raise DisposableTenantBackendError("database_connectivity_failed")
                cursor.execute(
                    "SELECT 1 FROM pg_extension WHERE extname='postgis'"
                )
                if cursor.fetchone() != (1,):
                    raise DisposableTenantBackendError("postgis_missing_after_schema")
                cursor.execute(
                    "SELECT COUNT(*) FROM django_migrations WHERE app='geoflow_ops'"
                )
                row = cursor.fetchone()
                if not row or int(row[0]) < 1:
                    raise DisposableTenantBackendError(
                        "tenant_migration_history_missing"
                    )
        finally:
            connection.close()

    # External/AWS/central-publication methods are intentionally unavailable in
    # this disposable backend. They are separate review boundaries.
    def ensure_external_secret(self, plan: TenantProvisioningPlan) -> bool:
        raise DisposableTenantBackendError("external_secret_backend_unavailable")

    def grant_runtime_exact_secret_read(self, plan: TenantProvisioningPlan) -> bool:
        raise DisposableTenantBackendError("runtime_iam_backend_unavailable")

    def verify_runtime_resolution_and_connectivity(
        self, plan: TenantProvisioningPlan
    ) -> None:
        raise DisposableTenantBackendError("runtime_verifier_unavailable")

    def publish_group_db_config(self, plan: TenantProvisioningPlan) -> None:
        raise DisposableTenantBackendError("central_publication_unavailable")

    def remove_runtime_secret_grant(self, plan: TenantProvisioningPlan) -> None:
        raise DisposableTenantBackendError("runtime_iam_backend_unavailable")

    def delete_external_secret(self, plan: TenantProvisioningPlan) -> None:
        raise DisposableTenantBackendError("external_secret_backend_unavailable")

    def drop_database(self, plan: TenantProvisioningPlan) -> None:
        connection = self._operation_connection()
        marker = self._database_marker(plan.db_name)
        if marker != self._marker(plan):
            raise DisposableTenantBackendError("database_ownership_marker_mismatch")
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT pg_terminate_backend(pid)
                  FROM pg_stat_activity
                 WHERE datname=%s AND pid <> pg_backend_pid()
                """,
                [plan.db_name],
            )
            cursor.execute(
                sql.SQL("DROP DATABASE {}").format(sql.Identifier(plan.db_name))
            )

    def drop_database_role(self, plan: TenantProvisioningPlan) -> None:
        connection = self._operation_connection()
        marker = self._role_marker(plan.db_user)
        if marker != self._marker(plan):
            raise DisposableTenantBackendError("role_ownership_marker_mismatch")
        with connection.cursor() as cursor:
            cursor.execute(
                sql.SQL("DROP ROLE {}").format(sql.Identifier(plan.db_user))
            )
