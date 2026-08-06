import uuid

import django.db.models.deletion
from django.db import migrations, models


SIGNUP_STATUSES = (
    "pending_email_verification",
    "pending_approval",
    "approved",
    "rejected",
    "withdrawn",
    "expired",
)

SIGNUP_EVENT_TYPES = (
    "submitted",
    "verified",
    "approved",
    "rejected",
    "withdrawn",
    "expired",
    "administrative_note",
)


class Migration(migrations.Migration):
    dependencies = [
        ("control", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="SignupRequest",
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
                    "status",
                    models.CharField(
                        choices=[
                            (value, value.replace("_", " ").title())
                            for value in SIGNUP_STATUSES
                        ],
                        max_length=32,
                    ),
                ),
                ("contact_phone", models.CharField(blank=True, max_length=32, null=True)),
                (
                    "organization_name",
                    models.CharField(blank=True, max_length=200, null=True),
                ),
                ("signup_purpose", models.CharField(max_length=1000)),
                ("terms_version", models.CharField(max_length=64)),
                ("terms_accepted_at", models.DateTimeField()),
                ("privacy_version", models.CharField(max_length=64)),
                ("privacy_accepted_at", models.DateTimeField()),
                ("submitted_at", models.DateTimeField()),
                ("decided_at", models.DateTimeField(blank=True, null=True)),
                (
                    "decision_reason_code",
                    models.CharField(blank=True, max_length=64, null=True),
                ),
                (
                    "decision_note",
                    models.CharField(blank=True, max_length=1000, null=True),
                ),
                ("version", models.PositiveIntegerField(default=1)),
                ("created_at", models.DateTimeField()),
                ("updated_at", models.DateTimeField()),
                (
                    "decided_by_user",
                    models.ForeignKey(
                        blank=True,
                        db_column="decided_by_user_id",
                        null=True,
                        on_delete=django.db.models.deletion.RESTRICT,
                        related_name="decided_signup_requests",
                        to="control.user",
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        db_column="user_id",
                        on_delete=django.db.models.deletion.RESTRICT,
                        related_name="signup_requests",
                        to="control.user",
                    ),
                ),
            ],
            options={
                "db_table": "signup_requests",
                "indexes": [
                    models.Index(
                        fields=["status", "submitted_at"],
                        name="signup_req_review_idx",
                    ),
                ],
                "constraints": [
                    models.CheckConstraint(
                        condition=models.Q(("status__in", SIGNUP_STATUSES)),
                        name="signup_req_status_valid",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(("version__gt", 0)),
                        name="signup_req_version_positive",
                    ),
                    models.UniqueConstraint(
                        condition=models.Q(
                            (
                                "status__in",
                                ("pending_email_verification", "pending_approval"),
                            )
                        ),
                        fields=("user",),
                        name="signup_req_one_open_user",
                    ),
                    models.CheckConstraint(
                        condition=(
                            models.Q(
                                ("decided_at__isnull", False),
                                ("decided_by_user__isnull", False),
                                ("status__in", ("approved", "rejected")),
                            )
                            | models.Q(
                                ("decided_at__isnull", False),
                                ("decided_by_user__isnull", True),
                                ("status__in", ("withdrawn", "expired")),
                            )
                            | models.Q(
                                ("decided_at__isnull", True),
                                ("decided_by_user__isnull", True),
                                (
                                    "status__in",
                                    ("pending_email_verification", "pending_approval"),
                                ),
                            )
                        ),
                        name="signup_req_decision_state",
                    ),
                ],
            },
        ),
        migrations.CreateModel(
            name="SignupRequestEvent",
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
                    "event_type",
                    models.CharField(
                        choices=[
                            (value, value.replace("_", " ").title())
                            for value in SIGNUP_EVENT_TYPES
                        ],
                        max_length=32,
                    ),
                ),
                (
                    "from_status",
                    models.CharField(
                        blank=True,
                        choices=[
                            (value, value.replace("_", " ").title())
                            for value in SIGNUP_STATUSES
                        ],
                        max_length=32,
                        null=True,
                    ),
                ),
                (
                    "to_status",
                    models.CharField(
                        choices=[
                            (value, value.replace("_", " ").title())
                            for value in SIGNUP_STATUSES
                        ],
                        max_length=32,
                    ),
                ),
                ("reason_code", models.CharField(blank=True, max_length=64, null=True)),
                ("note", models.CharField(blank=True, max_length=1000, null=True)),
                ("created_at", models.DateTimeField()),
                (
                    "actor_user",
                    models.ForeignKey(
                        blank=True,
                        db_column="actor_user_id",
                        null=True,
                        on_delete=django.db.models.deletion.RESTRICT,
                        related_name="signup_request_events",
                        to="control.user",
                    ),
                ),
                (
                    "signup_request",
                    models.ForeignKey(
                        db_column="signup_request_id",
                        on_delete=django.db.models.deletion.RESTRICT,
                        related_name="events",
                        to="control.signuprequest",
                    ),
                ),
            ],
            options={
                "db_table": "signup_request_events",
                "indexes": [
                    models.Index(
                        fields=["signup_request", "created_at", "id"],
                        name="signup_evt_history_idx",
                    ),
                    models.Index(fields=["created_at"], name="signup_evt_created_idx"),
                ],
                "constraints": [
                    models.CheckConstraint(
                        condition=models.Q(("event_type__in", SIGNUP_EVENT_TYPES)),
                        name="signup_evt_type_valid",
                    ),
                    models.CheckConstraint(
                        condition=(
                            models.Q(("from_status__isnull", True))
                            | models.Q(("from_status__in", SIGNUP_STATUSES))
                        ),
                        name="signup_evt_from_valid",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(("to_status__in", SIGNUP_STATUSES)),
                        name="signup_evt_to_valid",
                    ),
                ],
            },
        ),
    ]
