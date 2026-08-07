# control/views_signup.py
import logging

from django.contrib import messages
from django.shortcuts import redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.debug import (
    sensitive_post_parameters,
    sensitive_variables,
)
from django.views.decorators.http import require_http_methods

from .forms_signup import SignupRequestForm
from .services.signup_service import (
    SignupRequestInput,
    SignupRequestRejected,
    create_signup_request,
)
from .services.signup_verification_signup_outbox_service import (
    create_signup_request_with_verification_outbox,
)
from .services.signup_verification_outbox_feature import (
    signup_verification_outbox_enabled,
)
from .services.signup_verification_runtime import (
    verify_signup_email_from_runtime_config,
)
from .services.signup_verification_service import (
    EmailVerificationConfigurationError,
    EmailVerificationRejected,
)


logger = logging.getLogger(__name__)


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
@csrf_protect
def signup_view(request):
    if request.method == "POST":
        form = SignupRequestForm(request.POST)
        if form.is_valid():
            cleaned = form.cleaned_data
            signup_data = SignupRequestInput(
                email=cleaned["email"],
                password=cleaned["password"],
                name_display=cleaned["name_display"],
                contact_phone=cleaned["contact_phone"],
                organization_name=cleaned["organization_name"],
                signup_purpose=cleaned["signup_purpose"],
            )
            try:
                if signup_verification_outbox_enabled():
                    create_signup_request_with_verification_outbox(signup_data)
                else:
                    create_signup_request(signup_data)
            except SignupRequestRejected as exc:
                form.add_error(None, str(exc))
            else:
                messages.success(request, "가입 요청이 접수되었습니다. 승인 전에는 로그인할 수 없습니다.")
                return redirect("/login/")
    else:
        form = SignupRequestForm()

    return render(request, "control/signup.html", {"form": form})


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
