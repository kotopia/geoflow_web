import uuid

import django.db.models.deletion
from django.db import migrations, models


TOKEN_PURPOSES = (
    "signup_email_verification",
)

DIGEST_ALGORITHMS = (
    "hmac_sha256",
)


class Migration(migrations.Migration):
    dependencies = [
        ("control", "0002_signup_core_schema"),
    ]

    operations = [
        migrations.CreateModel(
            name="SignupEmailVerificationToken",
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
                    "purpose",
                    models.CharField(
                        choices=[
                            (value, value.replace("_", " ").title())
                            for value in TOKEN_PURPOSES
                        ],
                        max_length=64,
                    ),
                ),
                ("token_digest", models.CharField(max_length=64)),
                (
                    "digest_algorithm",
                    models.CharField(
                        choices=[
                            (value, value.replace("_", " ").title())
                            for value in DIGEST_ALGORITHMS
                        ],
                        default="hmac_sha256",
                        max_length=32,
                    ),
                ),
                ("digest_key_id", models.CharField(max_length=64)),
                ("expires_at", models.DateTimeField()),
                ("consumed_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField()),
                (
                    "signup_request",
                    models.ForeignKey(
                        db_column="signup_request_id",
                        on_delete=django.db.models.deletion.RESTRICT,
                        related_name="email_verification_tokens",
                        to="control.signuprequest",
                    ),
                ),
            ],
            options={
                "db_table": "signup_email_verification_tokens",
                "indexes": [
                    models.Index(
                        fields=["signup_request", "purpose", "expires_at"],
                        name="signup_vtoken_req_exp_idx",
                    ),
                    models.Index(
                        fields=["expires_at"],
                        name="signup_vtoken_exp_idx",
                    ),
                ],
                "constraints": [
                    models.CheckConstraint(
                        condition=models.Q(("purpose__in", TOKEN_PURPOSES)),
                        name="signup_vtoken_purpose_valid",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(
                            ("digest_algorithm__in", DIGEST_ALGORITHMS)
                        ),
                        name="signup_vtoken_digest_alg",
                    ),
                    models.UniqueConstraint(
                        fields=("digest_algorithm", "digest_key_id", "token_digest"),
                        name="signup_vtoken_digest_uq",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(
                            ("expires_at__gt", models.F("created_at"))
                        ),
                        name="signup_vtoken_expiry_order",
                    ),
                    models.CheckConstraint(
                        condition=(
                            models.Q(("consumed_at__isnull", True))
                            | models.Q(
                                ("consumed_at__gte", models.F("created_at"))
                            )
                        ),
                        name="signup_vtoken_used_order",
                    ),
                ],
            },
        ),
    ]
