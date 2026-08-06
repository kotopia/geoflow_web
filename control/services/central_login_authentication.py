from __future__ import annotations

from dataclasses import dataclass

from django.contrib.auth.hashers import check_password, identify_hasher, make_password


PUBLIC_LOGIN_ERROR = "이메일 또는 비밀번호가 올바르지 않습니다."
_DUMMY_PASSWORD_HASH = make_password("geoflow-login-dummy-password")


class CentralLoginPasswordConfigurationError(RuntimeError):
    """Internal failure that must not reveal verifier details to the client."""


@dataclass(frozen=True)
class CentralLoginPasswordResult:
    valid: bool
    needs_rehash: bool = False


def burn_central_login_password_check(password: str) -> None:
    """Reduce the timing difference for missing or inactive central accounts."""

    check_password(password or "", _DUMMY_PASSWORD_HASH)


def verify_central_login_password(
    password: str,
    encoded_password: str | None,
) -> CentralLoginPasswordResult:
    """Verify a central credential without producing account-specific public errors."""

    if not encoded_password or not str(encoded_password).strip():
        burn_central_login_password_check(password)
        return CentralLoginPasswordResult(valid=False)

    encoded = str(encoded_password)
    if encoded.startswith(("$2a$", "$2b$", "$2y$")):
        try:
            import bcrypt
        except Exception:
            raise CentralLoginPasswordConfigurationError(
                "legacy password verifier is unavailable"
            ) from None

        try:
            valid = bcrypt.checkpw(password.encode(), encoded.encode())
        except Exception:
            return CentralLoginPasswordResult(valid=False)
        return CentralLoginPasswordResult(valid=valid, needs_rehash=valid)

    try:
        valid = check_password(password, encoded)
    except Exception:
        return CentralLoginPasswordResult(valid=False)

    if not valid:
        return CentralLoginPasswordResult(valid=False)

    try:
        algorithm = identify_hasher(encoded).algorithm
    except Exception:
        algorithm = None

    return CentralLoginPasswordResult(
        valid=True,
        needs_rehash=algorithm not in (None, "pbkdf2_sha256"),
    )
