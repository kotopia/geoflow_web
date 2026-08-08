# control/views_signup.py
import logging
import os
from datetime import timedelta
from urllib.parse import urlsplit

from django.conf import settings
from django.contrib import messages
from django.shortcuts import redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.debug import (
    sensitive_post_parameters,
    sensitive_variables,
)
from django.views.decorators.http import require_http_methods

from .forms_signup import SignupRequestForm, SignupVerificationResendForm
from .legal_policy import (
    DEFAULT_PRIVACY_VERSION,
    DEFAULT_TERMS_VERSION,
    legal_document_version,
)
from .services.signup_service import (
    SignupRequestInput,
    SignupRequestRejected,
)
from .services.signup_verification_signup_outbox_service import (
    create_signup_request_with_verification_outbox,
)
from .services.signup_runtime_readiness import signup_public_runtime_ready
from .services.signup_verification_runtime import (
    verify_signup_email_from_runtime_config,
)
from .services.signup_verification_resend_outbox_service import (
    queue_signup_email_verification_resend,
)
from .services.signup_verification_service import (
    EmailVerificationConfigurationError,
    EmailVerificationRejected,
)
from .views_legal import legal_documents_ready


logger = logging.getLogger(__name__)
SIGNUP_UNAVAILABLE_MESSAGE = (
    "현재 회원가입을 사용할 수 없습니다. 잠시 후 다시 시도해 주세요."
)


@sensitive_post_parameters(
    "email",
    "password",
    "password_confirm",
    "name_display",
    "contact_phone",
    "organization_name",
    "signup_purpose",
    "invitation_code",
)
@sensitive_variables("cleaned", "signup_data")
@require_http_methods(["GET", "POST"])
@csrf_protect
@never_cache
def signup_view(request):
    signup_terms_url = _public_document_url("SIGNUP_TERMS_URL")
    signup_privacy_url = _public_document_url("SIGNUP_PRIVACY_URL")
    signup_available = bool(
        signup_public_runtime_ready()
        and signup_terms_url
        and signup_privacy_url
        and legal_documents_ready()
        and _legal_versions_current()
        and _legal_documents_confirmed()
    )

    if request.method == "POST":
        form = SignupRequestForm(request.POST)
        if not signup_available:
            form.add_error(None, SIGNUP_UNAVAILABLE_MESSAGE)
        elif form.is_valid():
            cleaned = form.cleaned_data
            signup_data = SignupRequestInput(
                email=cleaned["email"],
                password=cleaned["password"],
                name_display=cleaned["name_display"],
                contact_phone="",
                organization_name=cleaned["organization_name"],
                signup_purpose=cleaned["signup_purpose"],
                terms_agreed=cleaned["terms_agreed"],
                privacy_agreed=cleaned["privacy_agreed"],
            )
            try:
                create_signup_request_with_verification_outbox(signup_data)
            except SignupRequestRejected as exc:
                form.add_error(None, str(exc))
            else:
                messages.success(
                    request,
                    (
                        "가입 요청이 접수되었습니다. 이메일 인증을 완료한 후 "
                        "관리자 승인을 기다려 주세요."
                    ),
                )
                return redirect("/login/")
    else:
        form = SignupRequestForm()

    return render(
        request,
        "control/signup.html",
        {
            "form": form,
            "signup_available": signup_available,
            "signup_terms_url": signup_terms_url,
            "signup_privacy_url": signup_privacy_url,
            "signup_terms_version": legal_document_version(
                "SIGNUP_TERMS_VERSION",
                default=DEFAULT_TERMS_VERSION,
            ),
            "signup_privacy_version": legal_document_version(
                "SIGNUP_PRIVACY_VERSION",
                default=DEFAULT_PRIVACY_VERSION,
            ),
        },
        status=200 if signup_available else 503,
    )


@sensitive_post_parameters("email")
@require_http_methods(["GET", "POST"])
@csrf_protect
@never_cache
def signup_email_verification_resend_view(request):
    form = SignupVerificationResendForm(request.POST or None)
    resend_available = signup_public_runtime_ready()
    cooldown_seconds = getattr(
        settings,
        "SIGNUP_EMAIL_VERIFICATION_RESEND_COOLDOWN_SECONDS",
        None,
    )
    resend_available = bool(
        resend_available
        and isinstance(cooldown_seconds, int)
        and not isinstance(cooldown_seconds, bool)
        and cooldown_seconds > 0
    )

    if request.method == "POST":
        if not resend_available:
            form.add_error(None, SIGNUP_UNAVAILABLE_MESSAGE)
        elif form.is_valid():
            try:
                queue_signup_email_verification_resend(
                    form.cleaned_data["email"],
                    cooldown=timedelta(seconds=cooldown_seconds),
                )
            except Exception:
                # Do not expose whether the email exists or why queueing failed.
                logger.error("SIGNUP-RESEND: resend queue operation failed")
            messages.success(
                request,
                (
                    "인증메일 재전송 요청을 처리했습니다. 가입 인증 대상이고 "
                    "재전송 가능 시간이 지난 경우 메일이 발송됩니다."
                ),
            )
            return redirect("signup_resend")

    return render(
        request,
        "control/signup_email_verification_resend.html",
        {
            "form": form,
            "resend_available": resend_available,
        },
        status=200 if resend_available else 503,
    )


def _environment_or_setting_text(setting_name: str) -> str:
    """Resolve deploy-time public URL settings with environment precedence."""

    raw = os.environ.get(setting_name)
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    configured = getattr(settings, setting_name, None)
    if isinstance(configured, str) and configured.strip():
        return configured.strip()
    return ""


def _public_document_url(setting_name: str) -> str | None:
    expected_path = {
        "SIGNUP_TERMS_URL": "/terms/",
        "SIGNUP_PRIVACY_URL": "/privacy/",
    }.get(setting_name)
    if expected_path is None:
        return None

    value = _environment_or_setting_text(setting_name)
    if not value:
        return None
    parts = urlsplit(value)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        return None
    if parts.path != expected_path or parts.query or parts.fragment:
        return None

    site_origin = _environment_or_setting_text("SITE_ORIGIN")
    site_parts = urlsplit(site_origin)
    if site_parts.scheme not in ("http", "https") or not site_parts.netloc:
        return None
    if (
        site_parts.path not in ("", "/")
        or site_parts.query
        or site_parts.fragment
        or site_parts.username
        or site_parts.password
        or parts.username
        or parts.password
    ):
        return None
    if (parts.scheme.lower(), parts.netloc.lower()) != (
        site_parts.scheme.lower(),
        site_parts.netloc.lower(),
    ):
        return None
    if not getattr(settings, "DEBUG", False) and (
        parts.scheme != "https" or site_parts.scheme != "https"
    ):
        return None
    return value


def _legal_versions_current() -> bool:
    return (
        legal_document_version(
            "SIGNUP_TERMS_VERSION",
            default=DEFAULT_TERMS_VERSION,
        )
        == DEFAULT_TERMS_VERSION
        and legal_document_version(
            "SIGNUP_PRIVACY_VERSION",
            default=DEFAULT_PRIVACY_VERSION,
        )
        == DEFAULT_PRIVACY_VERSION
    )


def _legal_documents_confirmed() -> bool:
    configured = getattr(settings, "SIGNUP_LEGAL_DOCUMENTS_CONFIRMED", None)
    if configured is True:
        return True
    if configured is False:
        return False
    raw = os.environ.get("SIGNUP_LEGAL_DOCUMENTS_CONFIRMED")
    if not isinstance(raw, str):
        return False
    return raw.strip().lower() in {"1", "true", "yes", "y", "on"}


@sensitive_post_parameters("token")
@sensitive_variables("token")
@require_http_methods(["GET", "POST"])
@csrf_protect
@never_cache
def signup_email_verification_view(request):
    """Bridge a URL fragment token into a protected POST without URL logging."""

    if request.method == "GET":
        return _render_signup_verification(request, auto_submit=True)

    token = request.POST.get("token") or ""
    try:
        verify_signup_email_from_runtime_config(token)
    except EmailVerificationRejected:
        return _render_signup_verification(
            request,
            verification_failed=True,
            status=400,
        )
    except EmailVerificationConfigurationError:
        logger.error("SIGNUP-VERIFY: runtime configuration unavailable")
        return _render_signup_verification(
            request,
            verification_unavailable=True,
            status=503,
        )

    messages.success(
        request,
        (
            "이메일 인증이 완료되었습니다. "
            "관리자 승인 후 로그인할 수 있습니다."
        ),
    )
    return redirect("login")


def _render_signup_verification(request, *, status=200, **context):
    response = render(
        request,
        "control/signup_email_verification.html",
        context,
        status=status,
    )
    response["Referrer-Policy"] = "no-referrer"
    return response
