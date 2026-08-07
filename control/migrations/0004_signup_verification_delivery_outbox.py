import uuid

import django.db.models.deletion
from django.db import migrations, models


OUTBOX_DELIVERY_TYPES = (
    "signup_email_verification",
)

OUTBOX_STATUSES = (
    "pending",
    "processing",
    "delivered",
    "cancelled",
)


REVOKE_OLDER_UNCONSUMED_TOKENS_SQL = """
WITH ranked AS (
    SELECT id,
           ROW_NUMBER() OVER (
               PARTITION BY signup_request_id, purpose
               ORDER BY created_at DESC, id DESC
           ) AS position
      FROM signup_email_verification_tokens
     WHERE consumed_at IS NULL
)
UPDATE signup_email_verification_tokens AS token
   SET revoked_at=GREATEST(CURRENT_TIMESTAMP, token.created_at)
  FROM ranked
 WHERE token.id=ranked.id
   AND ranked.position > 1
   AND token.revoked_at IS NULL
"""


class Migration(migrations.Migration):
    dependencies = [
        ("control", "0003_signup_email_verification_tokens"),
    ]

    operations = [
        migrations.AddField(
            model_name="signupemailverificationtoken",
            name="revoked_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        # Irreversible by design: dropping revoked_at on rollback could make
        # previously superseded verification tokens usable again.
        migrations.RunSQL(
            sql=REVOKE_OLDER_UNCONSUMED_TOKENS_SQL,
        ),
        migrations.AddConstraint(
            model_name="signupemailverificationtoken",
            constraint=models.CheckConstraint(
                condition=(
                    models.Q(revoked_at__isnull=True)
                    | models.Q(revoked_at__gte=models.F("created_at"))
                ),
                name="signup_vtoken_revoked_order",
            ),
        ),
        migrations.AddConstraint(
            model_name="signupemailverificationtoken",
            constraint=models.CheckConstraint(
                condition=~(
                    models.Q(consumed_at__isnull=False)
                    & models.Q(revoked_at__isnull=False)
                ),
                name="signup_vtoken_one_terminal",
            ),
        ),
        migrations.AddConstraint(
            model_name="signupemailverificationtoken",
            constraint=models.UniqueConstraint(
                fields=("signup_request", "purpose"),
                condition=models.Q(
                    consumed_at__isnull=True,
                    revoked_at__isnull=True,
                ),
                name="signup_vtoken_one_live",
            ),
        ),
        migrations.CreateModel(
            name="SignupVerificationDeliveryOutbox",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                (
                    "delivery_type",
                    models.CharField(
                        choices=[
                            (value, value.replace("_", " ").title())
                            for value in OUTBOX_DELIVERY_TYPES
                        ],
                        max_length=64,
                    ),
                ),
                (
                    "status",
                    models.CharField(
                        choices=[
                            (value, value.replace("_", " ").title())
                            for value in OUTBOX_STATUSES
                        ],
                        max_length=32,
                    ),
                ),
                ("available_at", models.DateTimeField()),
                ("attempt_count", models.PositiveIntegerField(default=0)),
                ("lease_id", models.UUIDField(blank=True, null=True)),
                ("claimed_at", models.DateTimeField(blank=True, null=True)),
                ("claim_expires_at", models.DateTimeField(blank=True, null=True)),
                ("delivered_at", models.DateTimeField(blank=True, null=True)),
                (
                    "last_error_code",
                    models.CharField(blank=True, max_length=64, null=True),
                ),
                ("created_at", models.DateTimeField()),
                ("updated_at", models.DateTimeField()),
                (
                    "signup_request",
                    models.ForeignKey(
                        db_column="signup_request_id",
                        on_delete=django.db.models.deletion.RESTRICT,
                        related_name="verification_delivery_outbox",
                        to="control.signuprequest",
                    ),
                ),
            ],
            options={
                "db_table": "signup_verification_delivery_outbox",
                "indexes": [
                    models.Index(
                        fields=["status", "available_at"],
                        name="signup_outbox_due_idx",
                    ),
                    models.Index(
                        fields=["signup_request", "delivery_type", "created_at"],
                        name="signup_outbox_req_idx",
                    ),
                ],
                "constraints": [
                    models.CheckConstraint(
                        condition=models.Q(delivery_type__in=OUTBOX_DELIVERY_TYPES),
                        name="signup_outbox_type_valid",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(status__in=OUTBOX_STATUSES),
                        name="signup_outbox_status_valid",
                    ),
                    models.CheckConstraint(
                        condition=(
                            models.Q(
                                status="pending",
                                lease_id__isnull=True,
                                claimed_at__isnull=True,
                                claim_expires_at__isnull=True,
                                delivered_at__isnull=True,
                            )
                            | (
                                models.Q(
                                    status="processing",
                                    lease_id__isnull=False,
                                    claimed_at__isnull=False,
                                    claim_expires_at__isnull=False,
                                    delivered_at__isnull=True,
                                )
                                & models.Q(
                                    claim_expires_at__gt=models.F("claimed_at")
                                )
                            )
                            | models.Q(
                                status="delivered",
                                lease_id__isnull=True,
                                claimed_at__isnull=True,
                                claim_expires_at__isnull=True,
                                delivered_at__isnull=False,
                            )
                            | models.Q(
                                status="cancelled",
                                lease_id__isnull=True,
                                claimed_at__isnull=True,
                                claim_expires_at__isnull=True,
                                delivered_at__isnull=True,
                            )
                        ),
                        name="signup_outbox_state_valid",
                    ),
                    models.UniqueConstraint(
                        fields=("signup_request", "delivery_type"),
                        condition=models.Q(status__in=("pending", "processing")),
                        name="signup_outbox_one_active",
                    ),
                ],
            },
        ),
    ]
