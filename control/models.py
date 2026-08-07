import uuid

from django.db import models


SIGNUP_REQUEST_STATUSES = (
    "pending_email_verification",
    "pending_approval",
    "approved",
    "rejected",
    "withdrawn",
    "expired",
)

SIGNUP_REQUEST_EVENT_TYPES = (
    "submitted",
    "verified",
    "approved",
    "rejected",
    "withdrawn",
    "expired",
    "administrative_note",
)


class User(models.Model):
    id = models.UUIDField(primary_key=True)
    email = models.EmailField(unique=True)
    password_hash = models.TextField()
    name_display = models.TextField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    mfa_enabled = models.BooleanField(default=False)
    last_login = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField()
    updated_at = models.DateTimeField()

    class Meta:
        db_table = "users"
        managed = False

class Group(models.Model):
    id = models.UUIDField(primary_key=True)
    code = models.TextField(unique=True)
    name = models.TextField()
    status = models.TextField()
    created_at = models.DateTimeField()
    updated_at = models.DateTimeField()
    class Meta:
        db_table = "groups"
        managed = False

class Role(models.Model):
    id = models.UUIDField(primary_key=True)
    code = models.TextField(unique=True)
    name = models.TextField()
    class Meta:
        db_table = "roles"
        managed = False

class Permission(models.Model):
    id = models.UUIDField(primary_key=True)
    code = models.TextField(unique=True)
    class Meta:
        db_table = "permissions"
        managed = False

class RolePermission(models.Model):
    role = models.ForeignKey(Role, on_delete=models.CASCADE, db_column="role_id")
    permission = models.ForeignKey(Permission, on_delete=models.CASCADE, db_column="permission_id")
    class Meta:
        db_table = "role_permissions"
        unique_together = ("role", "permission")
        managed = False

class UserGroupMap(models.Model):
    id = models.UUIDField(primary_key=True)
    user = models.ForeignKey(User, on_delete=models.CASCADE, db_column="user_id")
    group = models.ForeignKey(Group, on_delete=models.CASCADE, db_column="group_id")
    role  = models.ForeignKey(Role, on_delete=models.RESTRICT, db_column="role_id")
    status = models.TextField()
    created_at = models.DateTimeField()
    updated_at = models.DateTimeField()
    class Meta:
        db_table = "user_group_map"
        unique_together = ("user", "group")
        managed = False

class GroupDBConfig(models.Model):
    group      = models.OneToOneField(Group, primary_key=True, on_delete=models.CASCADE, db_column="group_id")
    db_alias   = models.TextField(unique=True)
    db_name    = models.TextField()
    db_host    = models.TextField()
    db_port    = models.IntegerField()
    db_user    = models.TextField()
    db_password= models.TextField()
    # db_extra = models.JSONField(default=dict)  # 선택
    class Meta:
        db_table = "group_db_config"
        managed = False


class SignupRequest(models.Model):
    class Status(models.TextChoices):
        PENDING_EMAIL_VERIFICATION = "pending_email_verification"
        PENDING_APPROVAL = "pending_approval"
        APPROVED = "approved"
        REJECTED = "rejected"
        WITHDRAWN = "withdrawn"
        EXPIRED = "expired"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        User,
        on_delete=models.RESTRICT,
        db_column="user_id",
        related_name="signup_requests",
    )
    status = models.CharField(max_length=32, choices=Status.choices)
    contact_phone = models.CharField(max_length=32, null=True, blank=True)
    organization_name = models.CharField(max_length=200, null=True, blank=True)
    signup_purpose = models.CharField(max_length=1000)
    terms_version = models.CharField(max_length=64)
    terms_accepted_at = models.DateTimeField()
    privacy_version = models.CharField(max_length=64)
    privacy_accepted_at = models.DateTimeField()
    submitted_at = models.DateTimeField()
    decided_at = models.DateTimeField(null=True, blank=True)
    decided_by_user = models.ForeignKey(
        User,
        on_delete=models.RESTRICT,
        db_column="decided_by_user_id",
        related_name="decided_signup_requests",
        null=True,
        blank=True,
    )
    decision_reason_code = models.CharField(max_length=64, null=True, blank=True)
    decision_note = models.CharField(max_length=1000, null=True, blank=True)
    version = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField()
    updated_at = models.DateTimeField()

    class Meta:
        db_table = "signup_requests"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(status__in=SIGNUP_REQUEST_STATUSES),
                name="signup_req_status_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(version__gt=0),
                name="signup_req_version_positive",
            ),
            models.UniqueConstraint(
                fields=("user",),
                condition=models.Q(
                    status__in=("pending_email_verification", "pending_approval")
                ),
                name="signup_req_one_open_user",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(
                        status__in=("approved", "rejected"),
                        decided_at__isnull=False,
                        decided_by_user__isnull=False,
                    )               | models.Q(
                        status__in=("withdrawn", "expired"),
                        decided_at__isnull=False,
                        decided_by_user__isnull=True,
                    )
                    | models.Q(
                        status__in=("pending_email_verification", "pending_approval"),
                        decided_at__isnull=True,
                        decided_by_user__isnull=True,
                    )
                ),
                name="signup_req_decision_state",
            ),
        ]
        indexes = [
            models.Index(fields=("status", "submitted_at"), name="signup_req_review_idx"),
        ]


class SignupRequestEvent(models.Model):
    """Append-only signup transition history; normal services must never update rows."""

    class EventType(models.TextChoices):
        SUBMITTED = "submitted"
        VERIFIED = "verified"
        APPROVED = "approved"
        REJECTED = "rejected"
        WITHDRAWN = "withdrawn"
        EXPIRED = "expired"
        ADMINISTRATIVE_NOTE = "administrative_note"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    signup_request = models.ForeignKey(
        SignupRequest,
        on_delete=models.RESTRICT,
        db_column="signup_request_id",
        related_name="events",
    )
    event_type = models.CharField(max_length=32, choices=EventType.choices)
    from_status = models.CharField(
        max_length=32,
        choices=SignupRequest.Status.choices,
        null=True,
        blank=True,
    )
    to_status = models.CharField(max_length=32, choices=SignupRequest.Status.choices)
    actor_user = models.ForeignKey(
        User,
        on_delete=models.RESTRICT,
        db_column="actor_user_id",
        related_name="signup_request_events",
        null=True,
        blank=True,
    )
    reason_code = models.CharField(max_length=64, null=True, blank=True)
    note = models.CharField(max_length=1000, null=True, blank=True)
    created_at = models.DateTimeField()

    class Meta:
        db_table = "signup_request_events"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(event_type__in=SIGNUP_REQUEST_EVENT_TYPES),
                name="signup_evt_type_valid",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(from_status__isnull=True)
                    | models.Q(from_status__in=SIGNUP_REQUEST_STATUSES)
                ),
                name="signup_evt_from_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(to_status__in=SIGNUP_REQUEST_STATUSES),
                name="signup_evt_to_valid",
            ),
        ]
        indexes = [
            models.Index(
                fields=("signup_request", "created_at", "id"),
                name="signup_evt_history_idx",
            ),
            models.Index(fields=("created_at",), name="signup_evt_created_idx"),
        ]

SIGNUP_EMAIL_VERIFICATION_TOKEN_PURPOSES = (
    "signup_email_verification",
)

SIGNUP_EMAIL_VERIFICATION_DIGEST_ALGORITHMS = (
    "hmac_sha256",
)


class SignupEmailVerificationToken(models.Model):
    """Single-use signup email-verification grant; raw tokens must never be stored."""

    class Purpose(models.TextChoices):
        SIGNUP_EMAIL_VERIFICATION = "signup_email_verification"

    class DigestAlgorithm(models.TextChoices):
        HMAC_SHA256 = "hmac_sha256"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    signup_request = models.ForeignKey(
        SignupRequest,
        on_delete=models.RESTRICT,
        db_column="signup_request_id",
        related_name="email_verification_tokens",
    )
    purpose = models.CharField(max_length=64, choices=Purpose.choices)
    token_digest = models.CharField(max_length=64)
    digest_algorithm = models.CharField(
        max_length=32,
        choices=DigestAlgorithm.choices,
        default=DigestAlgorithm.HMAC_SHA256,
    )
    digest_key_id = models.CharField(max_length=64)
    expires_at = models.DateTimeField()
    consumed_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField()

    class Meta:
        db_table = "signup_email_verification_tokens"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(
                    purpose__in=SIGNUP_EMAIL_VERIFICATION_TOKEN_PURPOSES
                ),
                name="signup_vtoken_purpose_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    digest_algorithm__in=SIGNUP_EMAIL_VERIFICATION_DIGEST_ALGORITHMS
                ),
                name="signup_vtoken_digest_alg",
            ),
            models.UniqueConstraint(
                fields=("digest_algorithm", "digest_key_id", "token_digest"),
                name="signup_vtoken_digest_uq",
            ),
            models.CheckConstraint(
                condition=models.Q(expires_at__gt=models.F("created_at")),
                name="signup_vtoken_expiry_order",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(consumed_at__isnull=True)
                    | models.Q(consumed_at__gte=models.F("created_at"))
                ),
                name="signup_vtoken_used_order",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(revoked_at__isnull=True)
                    | models.Q(revoked_at__gte=models.F("created_at"))
                ),
                name="signup_vtoken_revoked_order",
            ),
            models.CheckConstraint(
                condition=~(
                    models.Q(consumed_at__isnull=False)
                    & models.Q(revoked_at__isnull=False)
                ),
                name="signup_vtoken_one_terminal",
            ),
            models.UniqueConstraint(
                fields=("signup_request", "purpose"),
                condition=models.Q(
                    consumed_at__isnull=True,
                    revoked_at__isnull=True,
                ),
                name="signup_vtoken_one_live",
            ),
        ]
        indexes = [
            models.Index(
                fields=("signup_request", "purpose", "expires_at"),
                name="signup_vtoken_req_exp_idx",
            ),
            models.Index(fields=("expires_at",), name="signup_vtoken_exp_idx"),
        ]


SIGNUP_VERIFICATION_DELIVERY_OUTBOX_TYPES = (
    "signup_email_verification",
)

SIGNUP_VERIFICATION_DELIVERY_OUTBOX_STATUSES = (
    "pending",
    "processing",
    "delivered",
    "cancelled",
)


class SignupVerificationDeliveryOutbox(models.Model):
    """Durable delivery intent; recipient and raw token are resolved at claim time."""

    class DeliveryType(models.TextChoices):
        SIGNUP_EMAIL_VERIFICATION = "signup_email_verification"

    class Status(models.TextChoices):
        PENDING = "pending"
        PROCESSING = "processing"
        DELIVERED = "delivered"
        CANCELLED = "cancelled"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    signup_request = models.ForeignKey(
        SignupRequest,
        on_delete=models.RESTRICT,
        db_column="signup_request_id",
        related_name="verification_delivery_outbox",
    )
    delivery_type = models.CharField(max_length=64, choices=DeliveryType.choices)
    status = models.CharField(max_length=32, choices=Status.choices)
    available_at = models.DateTimeField()
    attempt_count = models.PositiveIntegerField(default=0)
    lease_id = models.UUIDField(null=True, blank=True)
    claimed_at = models.DateTimeField(null=True, blank=True)
    claim_expires_at = models.DateTimeField(null=True, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    last_error_code = models.CharField(max_length=64, null=True, blank=True)
    created_at = models.DateTimeField()
    updated_at = models.DateTimeField()

    class Meta:
        db_table = "signup_verification_delivery_outbox"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(
                    delivery_type__in=SIGNUP_VERIFICATION_DELIVERY_OUTBOX_TYPES
                ),
                name="signup_outbox_type_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    status__in=SIGNUP_VERIFICATION_DELIVERY_OUTBOX_STATUSES
                ),
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
                        & models.Q(claim_expires_at__gt=models.F("claimed_at"))
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
        ]
        indexes = [
            models.Index(
                fields=("status", "available_at"),
                name="signup_outbox_due_idx",
            ),
            models.Index(
                fields=("signup_request", "delivery_type", "created_at"),
                name="signup_outbox_req_idx",
            ),
        ]
