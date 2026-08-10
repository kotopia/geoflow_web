from django.db import migrations


CREATE_PASSWORD_RESET_SCHEMA_SQL = r"""
CREATE TABLE account_password_reset_tokens (
    id uuid PRIMARY KEY,
    user_id uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    purpose varchar(64) NOT NULL,
    token_digest varchar(64) NOT NULL,
    digest_algorithm varchar(32) NOT NULL,
    digest_key_id varchar(64) NOT NULL,
    expires_at timestamptz NOT NULL,
    consumed_at timestamptz NULL,
    revoked_at timestamptz NULL,
    created_at timestamptz NOT NULL,
    CONSTRAINT account_prtoken_purpose_valid
        CHECK (purpose = 'account_password_reset'),
    CONSTRAINT account_prtoken_digest_alg
        CHECK (digest_algorithm = 'hmac_sha256'),
    CONSTRAINT account_prtoken_digest_uq
        UNIQUE (digest_algorithm, digest_key_id, token_digest),
    CONSTRAINT account_prtoken_expiry_order
        CHECK (expires_at > created_at),
    CONSTRAINT account_prtoken_used_order
        CHECK (consumed_at IS NULL OR consumed_at >= created_at),
    CONSTRAINT account_prtoken_revoked_order
        CHECK (revoked_at IS NULL OR revoked_at >= created_at),
    CONSTRAINT account_prtoken_one_terminal
        CHECK (NOT (consumed_at IS NOT NULL AND revoked_at IS NOT NULL))
);

CREATE UNIQUE INDEX account_prtoken_one_live
    ON account_password_reset_tokens(user_id, purpose)
    WHERE consumed_at IS NULL AND revoked_at IS NULL;

CREATE INDEX account_prtoken_user_exp_idx
    ON account_password_reset_tokens(user_id, purpose, expires_at);

CREATE INDEX account_prtoken_exp_idx
    ON account_password_reset_tokens(expires_at);

CREATE TABLE account_password_reset_delivery_outbox (
    id uuid PRIMARY KEY,
    user_id uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    delivery_type varchar(64) NOT NULL,
    status varchar(32) NOT NULL,
    available_at timestamptz NOT NULL,
    attempt_count integer NOT NULL DEFAULT 0,
    lease_id uuid NULL,
    claimed_at timestamptz NULL,
    claim_expires_at timestamptz NULL,
    delivered_at timestamptz NULL,
    last_error_code varchar(64) NULL,
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    CONSTRAINT account_proutbox_type_valid
        CHECK (delivery_type = 'account_password_reset'),
    CONSTRAINT account_proutbox_status_valid
        CHECK (status IN ('pending', 'processing', 'delivered', 'cancelled')),
    CONSTRAINT account_proutbox_attempt_nonnegative
        CHECK (attempt_count >= 0),
    CONSTRAINT account_proutbox_state_valid CHECK (
        (
            status = 'pending'
            AND lease_id IS NULL
            AND claimed_at IS NULL
            AND claim_expires_at IS NULL
            AND delivered_at IS NULL
        )
        OR (
            status = 'processing'
            AND lease_id IS NOT NULL
            AND claimed_at IS NOT NULL
            AND claim_expires_at IS NOT NULL
            AND claim_expires_at > claimed_at
            AND delivered_at IS NULL
        )
        OR (
            status = 'delivered'
            AND lease_id IS NULL
            AND claimed_at IS NULL
            AND claim_expires_at IS NULL
            AND delivered_at IS NOT NULL
        )
        OR (
            status = 'cancelled'
            AND lease_id IS NULL
            AND claimed_at IS NULL
            AND claim_expires_at IS NULL
            AND delivered_at IS NULL
        )
    )
);

CREATE UNIQUE INDEX account_proutbox_one_active
    ON account_password_reset_delivery_outbox(user_id, delivery_type)
    WHERE status IN ('pending', 'processing');

CREATE INDEX account_proutbox_due_idx
    ON account_password_reset_delivery_outbox(status, available_at);

CREATE INDEX account_proutbox_user_idx
    ON account_password_reset_delivery_outbox(user_id, delivery_type, created_at);
"""


DROP_PASSWORD_RESET_SCHEMA_SQL = r"""
DROP TABLE account_password_reset_delivery_outbox;
DROP TABLE account_password_reset_tokens;
"""


class Migration(migrations.Migration):
    dependencies = [
        ("control", "0005_join_request_decision_audit_columns"),
    ]

    operations = [
        migrations.RunSQL(
            sql=CREATE_PASSWORD_RESET_SCHEMA_SQL,
            reverse_sql=DROP_PASSWORD_RESET_SCHEMA_SQL,
        ),
    ]
