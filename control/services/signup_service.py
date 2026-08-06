from __future__ import annotations

import uuid
from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from typing import Protocol

from django.conf import settings
from django.contrib.auth.hashers import make_password
from django.db import IntegrityError, connections, transaction
from django.utils import timezone


PUBLIC_SIGNUP_ERROR = "가입 요청을 처리할 수 없습니다. 입력 내용을 확인하거나 관리자에게 문의하세요."


class SignupRequestRejected(Exception):
    """Public-safe rejection which must not disclose account existence."""


@dataclass(frozen=True)
class SignupRequestInput:
    email: str = field(repr=False)
    password: str = field(repr=False)
    name_display: str = field(repr=False)
    contact_phone: str = field(repr=False)
    organization_name: str = field(repr=False)
    signup_purpose: str = field(repr=False)


@dataclass(frozen=True)
class SignupRequestReceipt:
    """Non-secret identifiers produced by a committed signup request."""

    user_id: str = field(repr=False)
    signup_request_id: str = field(repr=False)


class SignupRepository(Protocol):
    def account_exists(self, email: str) -> bool: ...
    def create_inactive_user(self, **values) -> str: ...
    def create_signup_request(self, **values) -> str: ...
    def append_submitted_event(self, **values) -> None: ...


class CentralSignupRepository:
    def __init__(self, alias: str | None = None):
        self.alias = alias or getattr(settings, "CENTRAL_DB_ALIAS", "default")

    def account_exists(self, email: str) -> bool:
        with connections[self.alias].cursor() as cursor:
            cursor.execute(
                "SELECT 1 FROM users WHERE lower(email)=lower(%s) LIMIT 1",
                [email],
            )
            return cursor.fetchone() is not None

    def create_inactive_user(self, **values) -> str:
        user_id = str(uuid.uuid4())
        with connections[self.alias].cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO users (
                    id, email, password_hash, name_display,
                    is_active, email_verified, created_at, updated_at
                ) VALUES (%s, %s, %s, %s, FALSE, FALSE, %s, %s)
                """,
                [
                    user_id,
                    values["email"],
                    values["password_hash"],
                    values["name_display"],
                    values["created_at"],
                    values["created_at"],
                ],
            )
        return user_id

    def create_signup_request(self, **values) -> str:
        request_id = str(uuid.uuid4())
        with connections[self.alias].cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO signup_requests (
                    id, user_id, status, contact_phone, organization_name,
                    signup_purpose, terms_version, terms_accepted_at,
                    privacy_version, privacy_accepted_at, submitted_at,
                    version, created_at, updated_at
                ) VALUES (
                    %s, %s, 'pending_email_verification', %s, %s,
                    %s, %s, %s, %s, %s, %s, 1, %s, %s
                )
                """,
                [
                    request_id, values["user_id"], values["contact_phone"] or None,
                    values["organization_name"], values["signup_purpose"],
                    values["terms_version"], values["accepted_at"],
                    values["privacy_version"], values["accepted_at"],
                    values["accepted_at"], values["accepted_at"], values["accepted_at"],
                ],
            )
        return request_id

    def append_submitted_event(self, **values) -> None:
        with connections[self.alias].cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO signup_request_events (
                    id, signup_request_id, event_type, from_status,
                    to_status, actor_user_id, created_at
                ) VALUES (
                    %s, %s, 'submitted', NULL,
                    'pending_email_verification', NULL, %s
                )
                """,
                [str(uuid.uuid4()), values["signup_request_id"], values["created_at"]],
            )


def create_signup_request(
    data: SignupRequestInput,
    *,
    repository: SignupRepository | None = None,
    atomic_context: AbstractContextManager | None = None,
) -> SignupRequestReceipt:
    repository = repository or CentralSignupRepository()
    alias = getattr(repository, "alias", getattr(settings, "CENTRAL_DB_ALIAS", "default"))
    context = atomic_context or transaction.atomic(using=alias)
    now = timezone.now()
    password_hash = make_password(data.password)

    try:
        with context:
            if repository.account_exists(data.email):
                raise SignupRequestRejected(PUBLIC_SIGNUP_ERROR)

            user_id = repository.create_inactive_user(
                email=data.email,
                password_hash=password_hash,
                name_display=data.name_display,
                is_active=False,
                email_verified=False,
                created_at=now,
            )
            request_id = repository.create_signup_request(
                user_id=user_id,
                contact_phone=data.contact_phone,
                organization_name=data.organization_name,
                signup_purpose=data.signup_purpose,
                terms_version=getattr(settings, "SIGNUP_TERMS_VERSION", "phase1-v1"),
                privacy_version=getattr(settings, "SIGNUP_PRIVACY_VERSION", "phase1-v1"),
                accepted_at=now,
            )
            repository.append_submitted_event(
                signup_request_id=request_id,
                created_at=now,
            )

        return SignupRequestReceipt(
            user_id=user_id,
            signup_request_id=request_id,
        )
    except SignupRequestRejected:
        raise
    except IntegrityError as exc:
        raise SignupRequestRejected(PUBLIC_SIGNUP_ERROR) from exc
