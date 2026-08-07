from __future__ import annotations

from django.contrib import messages
from django.shortcuts import redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.debug import (
    sensitive_post_parameters,
    sensitive_variables,
)
from django.views.decorators.http import require_GET, require_POST

from .decorators import require_central_admin
from .services.signup_account_decision_service import (
    SignupAccountDecision,
    SignupAccountDecisionRejected,
    decide_signup_account,
)
from .services.signup_review_query_service import (
    get_pending_signup_review,
    list_pending_signup_reviews,
)
from .services_identity import lookup_user_id_from_request


@never_cache
@require_central_admin
@require_GET
def signup_reviews_admin(request):
    items = list_pending_signup_reviews(limit=100, offset=0)
    return render(request, "control/signup_reviews_admin.html", {"items": items})


@never_cache
@require_central_admin
@require_GET
def signup_review_detail_admin(request, req_id):
    item = get_pending_signup_review(str(req_id))
    if item is None:
        messages.error(request, "심사할 가입 요청을 찾을 수 없습니다.")
        return redirect("control:signup_reviews_admin")
    return render(
        request,
        "control/signup_review_detail_admin.html",
        {"item": item},
    )


@sensitive_post_parameters("note")
@sensitive_variables("note")
@require_POST
@require_central_admin
def signup_review_decide_admin(request, req_id, action):
    decision = {
        "approve": "approved",
        "reject": "rejected",
    }.get(action)
    if decision is None:
        messages.error(request, "올바르지 않은 심사 요청입니다.")
        return redirect("control:signup_reviews_admin")

    actor_user_id = lookup_user_id_from_request(request)
    expected_version = _positive_int(request.POST.get("version"))
    note = (request.POST.get("note") or "").strip() or None
    if actor_user_id is None or expected_version is None:
        messages.error(
            request,
            "가입 심사 상태를 확인한 뒤 다시 시도해 주세요.",
        )
        return redirect("control:signup_reviews_admin")

    try:
        decide_signup_account(
            SignupAccountDecision(
                signup_request_id=str(req_id),
                expected_version=expected_version,
                actor_user_id=str(actor_user_id),
                decision=decision,
                reason_code=None,
                note=note,
            )
        )
    except (SignupAccountDecisionRejected, ValueError):
        messages.error(request, "가입 심사 상태가 변경되어 처리할 수 없습니다.")
    else:
        if decision == "approved":
            messages.success(request, "가입 요청을 승인했습니다.")
        else:
            messages.success(request, "가입 요청을 거절했습니다.")

    return redirect("control:signup_reviews_admin")


def _positive_int(value) -> int | None:
    try:
        parsed = int(str(value))
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None
