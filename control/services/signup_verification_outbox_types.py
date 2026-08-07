from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


SIGNUP_VERIFICATION_DELIVERY_TYPE = "signup_email_verification"
OUTBOX_STATUS_PENDING = "pending"
OUTBOX_STATUS_PROCESSING = "processing"
OUTBOX_STATUS_DELIVERED = "delivered"
OUTBOX_STATUS_CANCELLED = "cancelled"
INELIGIBLE_OUTBOX_ERROR_CODE = "signup.ineligible"


@dataclass(frozen=True)
class SignupVerificationDeliveryClaim:
    outbox_id: str = field(repr=False)
    signup_request_id: str = field(repr=False)
    email: str = field(repr=False)
    lease_id: str = field(repr=False)
    attempt_count: int
    claim_expires_at: datetime


@dataclass(frozen=True)
class SignupVerificationLockedDeliveryTarget:
    signup_request_id: str = field(repr=False)
    email: str = field(repr=False)
