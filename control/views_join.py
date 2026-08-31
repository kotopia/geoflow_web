# control/views_join.py
import logging

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods

from control.decorators import require_central_admin
from control.services import central_repo as C
from control.services_identity import lookup_user_id_from_request
from control.services.join_membership_approval_service import (
    JoinMembershipApproval,
    JoinMembershipApprovalRejected,
    approve_join_membership,
)

CENTRAL = getattr(settings, "CENTRAL_DB_ALIAS", "default")
logger = logging.getLogger(__name__)


def _central_alias():
    return CENTRAL


@require_central_admin
def join_requests_pending_view(request):
    items = C.list_pending_join_requests()
    return render(request, "control/join_requests_pending.html", {"items": items})


@require_http_methods(["POST"])
@require_central_admin
def join_request_decide_view(request, req_id, action):
    """Approve/reject one central role request without provisioning identities."""

    jr = C.get_join_request(req_id)
    if not jr:
        messages.error(request, "요청을 찾을 수 없습니다.")
        return redirect("control:join_requests_pending")

    requested_email = (jr.get("requested_email") or "").strip().lower()
    group_id = jr.get("group_id")
    role_code = (jr.get("requested_role_code") or "").strip()

    decided_by = lookup_user_id_from_request(request)
    if not decided_by:
        messages.error(request, "요청을 처리할 수 없습니다. 관리자 상태를 확인하세요.")
        return redirect("control:join_requests_pending")

    if action == "reject":
        if jr.get("status") != "pending" or not C.reject_join_request_if_pending(
            req_id,
            decided_by=decided_by,
        ):
            messages.error(
                request,
                "요청을 처리할 수 없습니다. 요청 상태를 확인하세요.",
            )
            return redirect("control:join_requests_pending")
        messages.success(request, "요청을 거절했습니다.")
        return redirect("control:join_requests_pending")

    if action == "approve":
        if jr.get("status") != "pending":
            messages.error(
                request,
                "요청을 승인할 수 없습니다. 요청 상태를 확인하세요.",
            )
            return redirect("control:join_requests_pending")

        role_id = C.get_role_id_by_code(role_code)
        if not role_id:
            messages.error(
                request,
                "요청을 승인할 수 없습니다. 요청 상태를 확인하세요.",
            )
            return redirect("control:join_requests_pending")

        if not C.group_is_active(group_id):
            messages.error(
                request,
                "요청을 승인할 수 없습니다. 요청 상태를 확인하세요.",
            )
            return redirect("control:join_requests_pending")

        account = C.get_existing_user_account_by_email(requested_email)
        if not account or account.get("is_active") is not True:
            messages.error(
                request,
                "요청을 승인할 수 없습니다. 요청 상태를 확인하세요.",
            )
            return redirect("control:join_requests_pending")
        user_id = account["id"]

        try:
            approve_join_membership(
                JoinMembershipApproval(
                    request_id=str(req_id),
                    user_id=str(user_id),
                    group_id=str(group_id),
                    role_id=str(role_id),
                    actor_user_id=str(decided_by),
                )
            )
        except (JoinMembershipApprovalRejected, ValueError):
            messages.error(
                request,
                "요청을 승인할 수 없습니다. 요청 상태를 확인하세요.",
            )
            return redirect("control:join_requests_pending")
        except Exception:
            logger.warning("Join approval transaction failed")
            messages.error(
                request,
                "요청을 승인할 수 없습니다. 요청 상태를 확인하세요.",
            )
            return redirect("control:join_requests_pending")

        messages.success(request, "승인 완료")
        return redirect("control:join_requests_pending")

    messages.error(request, "올바르지 않은 요청입니다.")
    return redirect("control:join_requests_pending")


@login_required
def my_join_requests_view(request):
    me_email = (
        getattr(request.user, "email", None)
        or getattr(request.user, "username", None)
        or ""
    ).strip().lower()
    items = []
    me = C.get_user_by_email(me_email) if me_email else None
    if me:
        items = C.list_my_join_requests(me["id"])
    return render(request, "control/join_requests_my.html", {"items": items})
