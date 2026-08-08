from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from django.conf import settings
from django.db import connections


_REQUIRED_COLUMNS: dict[str, tuple[str, ...]] = {
    "users": (
        "id",
        "email",
        "password_hash",
        "name_display",
        "is_active",
        "email_verified",
        "is_staff",
        "mfa_enabled",
        "last_login",
        "created_at",
        "updated_at",
    ),
    "auth_user": (
        "id",
        "username",
        "email",
        "password",
        "first_name",
        "last_name",
        "last_login",
        "is_active",
        "is_staff",
        "is_superuser",
    ),
    "signup_requests": (
        "id",
        "user_id",
        "status",
        "contact_phone",
        "organization_name",
        "signup_purpose",
        "terms_version",
        "terms_accepted_at",
        "privacy_version",
        "privacy_accepted_at",
        "submitted_at",
        "decided_at",
        "decided_by_user_id",
        "decision_reason_code",
        "decision_note",
        "version",
        "created_at",
        "updated_at",
    ),
    "signup_request_events": (
        "id",
        "signup_request_id",
        "event_type",
        "from_status",
        "to_status",
        "actor_user_id",
        "reason_code",
        "note",
        "created_at",
    ),
    "signup_email_verification_tokens": (
        "id",
        "signup_request_id",
        "purpose",
        "token_digest",
        "digest_algorithm",
        "digest_key_id",
        "expires_at",
        "consumed_at",
        "revoked_at",
        "created_at",
    ),
    "signup_verification_delivery_outbox": (
        "id",
        "signup_request_id",
        "delivery_type",
        "status",
        "available_at",
        "attempt_count",
        "lease_id",
        "claimed_at",
        "claim_expires_at",
        "delivered_at",
        "last_error_code",
        "created_at",
        "updated_at",
    ),
    "groups": (
        "id",
        "code",
        "status",
    ),
    "roles": (
        "id",
        "code",
    ),
    "user_group_map": (
        "id",
        "user_id",
        "group_id",
        "role_id",
        "status",
    ),
    "join_requests": (
        "id",
        "user_id",
        "group_id",
        "requested_email",
        "requested_role_code",
        "status",
        "decided_at",
        "decided_by",
        "created_at",
        "updated_at",
    ),
}


_REQUIRED_UNIQUE_COLUMN_SETS: dict[str, tuple[frozenset[str], ...]] = {
    "users": (frozenset(("email",)),),
    "auth_user": (frozenset(("username",)),),
    "user_group_map": (frozenset(("user_id", "group_id")),),
    "join_requests": (
        frozenset(("user_id", "group_id", "requested_email")),
    ),
}

_REQUIRED_CONSTRAINTS: dict[str, tuple[str, ...]] = {
    "signup_requests": (
        "signup_req_status_valid",
        "signup_req_version_positive",
        "signup_req_decision_state",
    ),
    "signup_request_events": (
        "signup_evt_type_valid",
        "signup_evt_from_valid",
        "signup_evt_to_valid",
    ),
    "signup_email_verification_tokens": (
        "signup_vtoken_purpose_valid",
        "signup_vtoken_digest_alg",
        "signup_vtoken_digest_uq",
        "signup_vtoken_expiry_order",
        "signup_vtoken_used_order",
        "signup_vtoken_revoked_order",
        "signup_vtoken_one_terminal",
    ),
    "signup_verification_delivery_outbox": (
        "signup_outbox_type_valid",
        "signup_outbox_status_valid",
        "signup_outbox_state_valid",
    ),
}

_REQUIRED_INDEXES: dict[str, tuple[str, ...]] = {
    "signup_requests": (
        "signup_req_review_idx",
        "signup_req_one_open_user",
    ),
    "signup_request_events": (
        "signup_evt_history_idx",
        "signup_evt_created_idx",
    ),
    "signup_email_verification_tokens": (
        "signup_vtoken_req_exp_idx",
        "signup_vtoken_exp_idx",
        "signup_vtoken_one_live",
    ),
    "signup_verification_delivery_outbox": (
        "signup_outbox_due_idx",
        "signup_outbox_req_idx",
        "signup_outbox_one_active",
    ),
}


@dataclass(frozen=True)
class SignupSchemaReadiness:
    ready: bool
    issues: tuple[str, ...]


class SignupSchemaReadinessRepository(Protocol):
    def inspect(self) -> SignupSchemaReadiness: ...


class SqlSignupSchemaReadinessRepository:
    """Read-only structural audit for the central signup launch boundary."""

    def __init__(self, alias: str | None = None):
        self.alias = alias or getattr(settings, "CENTRAL_DB_ALIAS", "default")

    def _table_exists(self, cursor, table: str) -> bool:
        cursor.execute("SELECT to_regclass(%s)", [f"public.{table}"])
        row = cursor.fetchone()
        return bool(row and row[0])

    def _columns(self, cursor, table: str) -> set[str]:
        cursor.execute(
            """
            SELECT column_name
              FROM information_schema.columns
             WHERE table_schema='public'
               AND table_name=%s
            """,
            [table],
        )
        return {str(row[0]) for row in cursor.fetchall()}

    def _constraints(self, cursor, table: str) -> set[str]:
        cursor.execute(
            """
            SELECT constraint_name
              FROM information_schema.table_constraints
             WHERE table_schema='public'
               AND table_name=%s
            """,
            [table],
        )
        return {str(row[0]) for row in cursor.fetchall()}

    def _indexes(self, cursor, table: str) -> set[str]:
        cursor.execute(
            """
            SELECT indexname
              FROM pg_indexes
             WHERE schemaname='public'
               AND tablename=%s
            """,
            [table],
        )
        return {str(row[0]) for row in cursor.fetchall()}

    def _unique_index_column_sets(
        self, cursor, table: str
    ) -> set[frozenset[str]]:
        cursor.execute(
            """
            SELECT array_agg(attribute.attname ORDER BY key_column.ordinality)
              FROM pg_index AS index_meta
              JOIN pg_class AS table_meta
                ON table_meta.oid=index_meta.indrelid
              JOIN pg_namespace AS namespace_meta
                ON namespace_meta.oid=table_meta.relnamespace
              CROSS JOIN LATERAL unnest(index_meta.indkey) WITH ORDINALITY
                AS key_column(attnum, ordinality)
              JOIN pg_attribute AS attribute
                ON attribute.attrelid=table_meta.oid
               AND attribute.attnum=key_column.attnum
             WHERE namespace_meta.nspname='public'
               AND table_meta.relname=%s
               AND index_meta.indisunique=TRUE
               AND index_meta.indpred IS NULL
             GROUP BY index_meta.indexrelid
            """,
            [table],
        )
        return {
            frozenset(str(column) for column in row[0])
            for row in cursor.fetchall()
            if row and row[0]
        }

    def inspect(self) -> SignupSchemaReadiness:
        issues: list[str] = []
        with connections[self.alias].cursor() as cursor:
            columns_by_table: dict[str, set[str]] = {}
            for table, required_columns in _REQUIRED_COLUMNS.items():
                if not self._table_exists(cursor, table):
                    issues.append(f"missing_table:{table}")
                    continue
                columns = self._columns(cursor, table)
                columns_by_table[table] = columns
                for column in required_columns:
                    if column not in columns:
                        issues.append(f"missing_column:{table}.{column}")

            for table, required_constraints in _REQUIRED_CONSTRAINTS.items():
                if table not in columns_by_table:
                    continue
                constraints = self._constraints(cursor, table)
                for constraint in required_constraints:
                    if constraint not in constraints:
                        issues.append(f"missing_constraint:{table}.{constraint}")

            for table, required_indexes in _REQUIRED_INDEXES.items():
                if table not in columns_by_table:
                    continue
                indexes = self._indexes(cursor, table)
                for index in required_indexes:
                    if index not in indexes:
                        issues.append(f"missing_index:{table}.{index}")

            for table, required_column_sets in _REQUIRED_UNIQUE_COLUMN_SETS.items():
                if table not in columns_by_table:
                    continue
                available_sets = self._unique_index_column_sets(cursor, table)
                for required_columns in required_column_sets:
                    if required_columns not in available_sets:
                        label = ",".join(sorted(required_columns))
                        issues.append(f"missing_unique:{table}.{label}")

            signup_presence = [
                table in columns_by_table
                for table in (
                    "signup_requests",
                    "signup_request_events",
                    "signup_email_verification_tokens",
                    "signup_verification_delivery_outbox",
                )
            ]
            if any(signup_presence) and not all(signup_presence):
                issues.append("partial_signup_schema")

        normalized = tuple(sorted(set(issues)))
        return SignupSchemaReadiness(ready=not normalized, issues=normalized)


def inspect_signup_schema_readiness(
    *,
    repository: SignupSchemaReadinessRepository | None = None,
) -> SignupSchemaReadiness:
    repository = repository or SqlSignupSchemaReadinessRepository()
    return repository.inspect()
