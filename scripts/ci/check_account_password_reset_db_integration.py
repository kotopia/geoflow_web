from __future__ import annotations

import os
import sys
import uuid
from datetime import timedelta
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

# Executing this file directly makes scripts/ci the first import path. Put the
# reviewed repository root first so Django settings and application modules are
# imported from the checkout under test rather than from the runner environment.
REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPOSITORY_ROOT))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "geoflow_project.ci_migration_settings")

import django  # noqa: E402

django.setup()

from django.conf import settings  # noqa: E402
from django.contrib.auth.hashers import check_password, make_password  # noqa: E402
from django.db import connections, transaction  # noqa: E402
from django.utils import timezone  # noqa: E402

from control.services.account_password_reset_outbox_service import (  # noqa: E402
    claim_next_account_password_reset_delivery,
    process_account_password_reset_delivery_claim,
    queue_account_password_reset_request,
)
from control.services.account_password_reset_service import (  # noqa: E402
    AccountPasswordResetRejected,
    reset_account_password_with_token,
)
from control.services.signup_verification_token_service import (  # noqa: E402
    HmacSha256VerificationKeyRing,
)


TEST_USER_ID = uuid.UUID("44444444-4444-4444-8444-444444444444")
TEST_EMAIL = "password-reset-ci@example.invalid"
OLD_PASSWORD = "OldIntegration-2026!Zebra"
NEW_PASSWORD = "NewIntegration-2026!Zebra"
TOKEN_SECRET = "B" * 43
LEASE_ID = uuid.UUID("55555555-5555-4555-8555-555555555555")


def fail(reason: str) -> None:
    print(f"password_reset_db_integration_blocker={reason}")
    raise SystemExit(2)


def main() -> int:
    alias = getattr(settings, "CENTRAL_DB_ALIAS", "default")
    now = timezone.now()
    delivered: dict[str, object] = {}
    key_ring = HmacSha256VerificationKeyRing(
        active_key_id="ci",
        keys={"ci": b"A" * 32},
    )

    def fake_deliver(**kwargs):
        delivered.update(kwargs)

    with transaction.atomic(using=alias):
        with connections[alias].cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO users (
                    id, email, password_hash, name_display,
                    is_active, email_verified, is_staff, mfa_enabled,
                    created_at, updated_at
                ) VALUES (%s, %s, %s, NULL, TRUE, TRUE, FALSE, FALSE, %s, %s)
                """,
                [TEST_USER_ID, TEST_EMAIL, make_password(OLD_PASSWORD), now, now],
            )

        queued = queue_account_password_reset_request(
            TEST_EMAIL,
            cooldown=timedelta(minutes=10),
            alias=alias,
            clock=lambda: now,
        )
        if not queued:
            fail("initial_request_not_queued")

        duplicate = queue_account_password_reset_request(
            TEST_EMAIL.upper(),
            cooldown=timedelta(minutes=10),
            alias=alias,
            clock=lambda: now,
        )
        if duplicate:
            fail("cooldown_duplicate_was_queued")

        claim = claim_next_account_password_reset_delivery(
            lease_for=timedelta(seconds=120),
            alias=alias,
            clock=lambda: now,
            lease_factory=lambda: LEASE_ID,
        )
        if claim is None:
            fail("outbox_claim_missing")
        if claim.user_id != str(TEST_USER_ID) or claim.email != TEST_EMAIL:
            fail("outbox_claim_identity_mismatch")
        if claim.attempt_count != 1:
            fail("outbox_attempt_count_mismatch")

        process_clock = now
        outcome = process_account_password_reset_delivery_claim(
            claim,
            reset_url="https://geoflow.co.kr/password/reset/",
            ttl=timedelta(hours=1),
            retry_at=process_clock + timedelta(minutes=5),
            key_ring=key_ring,
            alias=alias,
            clock=lambda: process_clock,
            token_factory=lambda _size: TOKEN_SECRET,
            deliver=fake_deliver,
            email_timeout_seconds=30,
            max_attempts=5,
            settings_obj=settings,
        )
        if outcome != "delivered":
            fail("outbox_delivery_not_marked_delivered")

        reset_link = str(delivered.get("reset_link") or "")
        split = urlsplit(reset_link)
        if split.scheme != "https" or split.netloc != "geoflow.co.kr":
            fail("reset_link_origin_mismatch")
        if split.query:
            fail("reset_token_leaked_to_query")
        fragment = parse_qs(split.fragment, keep_blank_values=True)
        raw_token = (fragment.get("token") or [""])[0]
        if not raw_token.startswith("pr1.ci."):
            fail("reset_fragment_token_missing")

        with connections[alias].cursor() as cursor:
            cursor.execute(
                """
                SELECT status, attempt_count, delivered_at IS NOT NULL
                  FROM account_password_reset_delivery_outbox
                 WHERE user_id=%s
                """,
                [TEST_USER_ID],
            )
            outbox_row = cursor.fetchone()
            if outbox_row != ("delivered", 1, True):
                fail("outbox_terminal_state_invalid")

            cursor.execute(
                """
                SELECT token_digest, consumed_at, revoked_at
                  FROM account_password_reset_tokens
                 WHERE user_id=%s
                   AND purpose='account_password_reset'
                """,
                [TEST_USER_ID],
            )
            token_row = cursor.fetchone()
            if token_row is None:
                fail("password_reset_digest_missing")
            if token_row[0] == raw_token or len(str(token_row[0])) != 64:
                fail("raw_token_was_persisted")
            if token_row[1] is not None or token_row[2] is not None:
                fail("fresh_token_not_live")

        result = reset_account_password_with_token(
            token=raw_token,
            new_password=NEW_PASSWORD,
            key_ring=key_ring,
            alias=alias,
        )
        if result.user_id != str(TEST_USER_ID):
            fail("reset_result_identity_mismatch")

        with connections[alias].cursor() as cursor:
            cursor.execute(
                "SELECT password_hash FROM users WHERE id=%s",
                [TEST_USER_ID],
            )
            password_row = cursor.fetchone()
            if password_row is None or not check_password(NEW_PASSWORD, password_row[0]):
                fail("central_password_hash_not_updated")
            cursor.execute(
                """
                SELECT consumed_at IS NOT NULL, revoked_at IS NULL
                  FROM account_password_reset_tokens
                 WHERE user_id=%s
                   AND purpose='account_password_reset'
                """,
                [TEST_USER_ID],
            )
            consumed_row = cursor.fetchone()
            if consumed_row != (True, True):
                fail("reset_token_not_consumed_once")

        try:
            reset_account_password_with_token(
                token=raw_token,
                new_password="ReplayIntegration-2026!Zebra",
                key_ring=key_ring,
                alias=alias,
            )
        except AccountPasswordResetRejected:
            pass
        else:
            fail("reset_token_replay_was_accepted")

        transaction.set_rollback(True, using=alias)

    print("password_reset_db_integration_request_cooldown=yes")
    print("password_reset_db_integration_outbox_delivery=yes")
    print("password_reset_db_integration_fragment_only_token=yes")
    print("password_reset_db_integration_digest_only_storage=yes")
    print("password_reset_db_integration_password_update=yes")
    print("password_reset_db_integration_replay_rejected=yes")
    print("password_reset_db_integration_rolled_back=yes")
    print("password_reset_db_integration_complete=yes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
