from __future__ import annotations

from django.conf import settings
from django.contrib import messages
from django.core.validators import validate_email
from django.core.exceptions import ValidationError
from django.shortcuts import render
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_exempt, csrf_protect
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_http_methods

from .services.account_password_reset_delivery import (
    AccountPasswordResetConfigurationError,
    load_account_password_reset_delivery_config,
)
from .services.account_password_reset_outbox_service import (
    queue_account_password_reset_request,
)
from .services.account_password_reset_service import (
    AccountPasswordResetError,
    AccountPasswordResetRejected,
    reset_account_password_with_token,
)
from .services.signup_verification_runtime import (
    load_signup_email_verification_key_ring,
)
from .services.signup_verification_service import (
    EmailVerificationConfigurationError,
)


GENERIC_RESET_REQUEST_MESSAGE = (
    "입력한 이메일로 재설정할 수 있는 계정이 있으면 안내 메일을 발송합니다. "
    "메일이 보이지 않으면 잠시 후 스팸함도 확인해 주세요."
)


@sensitive_post_parameters("email")
@never_cache
@csrf_protect
@require_http_methods(["GET", "POST"])
def forgot_password_view(request):
    if request.method == "GET":
        return render(request, "control/forgot_password.html")

    email = str(request.POST.get("email") or "").strip().lower()
    try:
        validate_email(email)
    except ValidationError:
        return render(
            request,
            "control/forgot_password.html",
            {"form_error": "올바른 이메일 주소를 입력해 주세요."},
            status=400,
        )

    try:
        config = load_account_password_reset_delivery_config(settings_obj=settings)
        # Loading the key ring here makes a broken reset configuration fail before
        # a delivery intent is persisted, without exposing whether the account exists.
        load_signup_email_verification_key_ring(settings_obj=settings)
        queue_account_password_reset_request(
            email,
            cooldown=config.request_cooldown,
        )
    except (AccountPasswordResetConfigurationError, EmailVerificationConfigurationError):
        return render(
            request,
            "control/forgot_password.html",
            {"service_error": "현재 비밀번호 재설정 요청을 처리할 수 없습니다."},
            status=503,
        )

    return render(
        request,
        "control/forgot_password.html",
        {"submitted": True, "status_message": GENERIC_RESET_REQUEST_MESSAGE},
    )


# The raw reset token is a one-time, expiring, replay-protected capability and
# arrives from an email fragment. Keep this exemption scoped to the reset endpoint;
# the reset-request form and every other account form remain CSRF-protected.
@sensitive_post_parameters("token", "new_password", "new_password2")
@never_cache
@csrf_exempt
@require_http_methods(["GET", "POST"])
def reset_password_view(request):
    if request.method == "GET":
        return render(request, "control/reset_password.html")

    token = str(request.POST.get("token") or "").strip()
    new_password = str(request.POST.get("new_password") or "")
    new_password2 = str(request.POST.get("new_password2") or "")
    if not token:
        return render(
            request,
            "control/reset_password.html",
            {"reset_error": "재설정 링크가 유효하지 않거나 만료되었습니다."},
            status=400,
        )
    if not new_password or new_password != new_password2:
        return render(
            request,
            "control/reset_password.html",
            {
                "posted_token": token,
                "password_error": "새 비밀번호가 비어 있거나 서로 일치하지 않습니다.",
            },
            status=400,
        )

    try:
        key_ring = load_signup_email_verification_key_ring(settings_obj=settings)
        reset_account_password_with_token(
            token=token,
            new_password=new_password,
            key_ring=key_ring,
        )
    except EmailVerificationConfigurationError:
        return render(
            request,
            "control/reset_password.html",
            {"service_error": "현재 비밀번호 재설정을 완료할 수 없습니다."},
            status=503,
        )
    except AccountPasswordResetRejected:
        return render(
            request,
            "control/reset_password.html",
            {
                "posted_token": token,
                "reset_error": (
                    "재설정 링크가 유효하지 않거나 만료되었거나, "
                    "새 비밀번호가 보안 조건을 만족하지 않습니다."
                ),
            },
            status=400,
        )
    except AccountPasswordResetError:
        return render(
            request,
            "control/reset_password.html",
            {"service_error": "현재 비밀번호 재설정을 완료할 수 없습니다."},
            status=503,
        )

    messages.success(request, "비밀번호가 변경되었습니다. 새 비밀번호로 로그인해 주세요.")
    return render(request, "control/reset_password_complete.html")
