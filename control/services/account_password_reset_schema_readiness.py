from __future__ import annotations

from dataclasses import dataclass

from django.conf import settings
from django.db import connections


TOKEN_TABLE = "account_password_reset_tokens"
OUTBOX_TABLE = "account_password_reset_delivery_outbox"

_REQUIRED_COLUMNS = {
    TOKEN_TABLE: {
        "id",
        "user_id",
        "purpose",
        "token_digest",
        "digest_algorithm",
        "digest_key_id",
        "expires_at",
        "consumed_at",
        "revoked_at",
        "created_at",
    },
    OUTBOX_TABLE: {
        "id",
        "user_id",
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
    },
}

_REQUIRED_INDEXES = {
    "account_prtoken_digest_uq",
    "account_prtoken_one_live",
    "account_prtoken_user_exp_idx",
    "account_proutbox_one_active",
    "account_proutbox_due_idx",
}


@dataclass(frozen=True)
class AccountPasswordResetSchemaReadiness:
    ready: bool
    issues: tuple[str, ...]


def inspect_account_password_reset_schema_readiness(
    *, alias: str | None = None
) -> AccountPasswordResetSchemaReadiness:
    """Read only the central catalog; never inspect rows or credentials."""

    resolved_alias = alias or getattr(settings, "CENTRAL_DB_ALIAS", "default")
    issues: list[str] = []

    with connections[resolved_alias].cursor() as cursor:
        for table_name, required_columns in _REQUIRED_COLUMNS.items():
            cursor.execute(
                """
                SELECT column_name
                  FROM information_schema.columns
                 WHERE table_schema='public'
                   AND table_name=%s
                """,
                [table_name],
            )
            existing_columns = {str(row[0]) for row in cursor.fetchall()}
            if not existing_columns:
                issues.append(f"missing_table:{table_name}")
                continue
            for column_name in sorted(required_columns - existing_columns):
                issues.append(f"missing_column:{table_name}.{column_name}")

        cursor.execute(
            """
            SELECT indexname
              FROM pg_indexes
             WHERE schemaname='public'
               AND tablename IN (%s, %s)
            """,
            [TOKEN_TABLE, OUTBOX_TABLE],
        )
        existing_indexes = {str(row[0]) for row in cursor.fetchall()}
        for index_name in sorted(_REQUIRED_INDEXES - existing_indexes):
            issues.append(f"missing_index:{index_name}")

        cursor.execute(
            """
            SELECT 1
              FROM django_migrations
             WHERE app='control'
               AND name='0006_account_password_reset_schema'
             LIMIT 1
            """
        )
        if cursor.fetchone() is None:
            issues.append("missing_migration:control.0006_account_password_reset_schema")

    return AccountPasswordResetSchemaReadiness(
        ready=not issues,
        issues=tuple(issues),
    )
