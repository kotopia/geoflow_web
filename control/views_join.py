# control/views_join.py
from uuid import uuid4
import logging

from django.conf import settings
from django.shortcuts import render, redirect
from django.contrib import messages
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_POST, require_http_methods
from django.db import connections, transaction
from django.contrib.auth.decorators import login_required
from django.urls import reverse

from control.services import emailer as Mail
from control.decorators import require_central_admin  # 중앙 전용 보호 데코레이터
from control.services import central_repo as C
from control.services import tenant_repo as T
from control.services.central_repo import JoinRequestStateConflict

CENTRAL = getattr(settings, "CENTRAL_DB_ALIAS", "default")
logger = logging.getLogger(__name__)

def _central_alias():
    return CENTRAL


# 중앙: 대기 중 권한요청 목록
@require_central_admin
def join_requests_pending_view(request):
    items = C.list_pending_join_requests()
    return render(request, "control/join_requests_pending.html", {"items": items})


# 중앙: 승인/거절 처리
@require_http_methods(["POST"])
@require_central_admin
def join_request_decide_view(request, req_id, action):
    """
    중앙 관리자가 권한요청을 승인/거절한다.
    - approve:
        1) 요청 로드
        2) existing active user 확인
        3) user_group_map upsert
        4) 요청 상태 approved (decided_by 기록)
        5) 비밀번호 없으면 set-password 메일 발송
    - reject:
        요청 상태 rejected (decided_by 기록)
    """
    # 1) 요청 로드
    jr = C.get_join_request(req_id)  # dict: {id, user_id, group_id, requested_email, requested_role_code, ...}
    if not jr:
        messages.error(request, "요청을 찾을 수 없습니다.")
        return redirect("join_requests_pending")

    requested_email = (jr.get("requested_email") or "").strip().lower()
    group_id = jr.get("group_id")
    role_code = (jr.get("requested_role_code") or "").strip()

    # 중앙 관리자 id (결정자 기록)
    admin_email = (getattr(request.user, "email", None) or getattr(request.user, "username", "")).strip().lower()
    admin_user = C.get_user_by_email(admin_email) if admin_email else None
    decided_by = admin_user["id"] if admin_user else None

    if action == "reject":
        if jr.get("status") != "pending" or not C.reject_join_request_if_pending(
            req_id,
            decided_by=decided_by,
        ):
            messages.error(request, "요청을 처리할 수 없습니다. 요청 상태를 확인하세요.")
            return redirect("join_requests_pending")
        messages.success(request, "요청을 거절했습니다.")
        return redirect("join_requests_pending")

    if action == "approve":
        if jr.get("status") != "pending":
            messages.error(request, "요청을 승인할 수 없습니다. 요청 상태를 확인하세요.")
            return redirect("join_requests_pending")

        # 2) 역할, 그룹, 기존 active 계정 확인
        role_id = C.get_role_id_by_code(role_code)
        if not role_id:
            messages.error(request, "요청을 승인할 수 없습니다. 요청 상태를 확인하세요.")
            return redirect("join_requests_pending")

        if not C.group_is_active(group_id):
            messages.error(request, "요청을 승인할 수 없습니다. 요청 상태를 확인하세요.")
            return redirect("join_requests_pending")

        account = C.get_existing_user_account_by_email(requested_email)
        if not account or account.get("is_active") is not True:
            messages.error(request, "요청을 승인할 수 없습니다. 요청 상태를 확인하세요.")
            return redirect("join_requests_pending")
        user_id = account["id"]

        # 3~4) 멤버십과 pending -> approved 전이를 같은 중앙 transaction에서 처리
        try:
            C.approve_join_request_membership(
                req_id,
                user_id=user_id,
                group_id=group_id,
                role_id=role_id,
                decided_by=decided_by,
            )
        except JoinRequestStateConflict:
            messages.error(request, "요청을 승인할 수 없습니다. 요청 상태를 확인하세요.")
            return redirect("join_requests_pending")
        except Exception:
            logger.warning("Join approval transaction failed")
            messages.error(request, "요청을 승인할 수 없습니다. 요청 상태를 확인하세요.")
            return redirect("join_requests_pending")

        # (선택) 테넌트 role_code 동기화가 필요하다면 여기서 tenant_repo를 호출하세요.
        # 예: T.sync_employee_role_by_email(group_id, requested_email, role_code)

        # 5) DB 승인 commit 이후 비밀번호가 없는 active user에게만 token/mail 처리
        try:
            if not C.user_has_password(user_id):
                token = C.create_set_password_token(user_id)  # 24시간 유효
                link = request.build_absolute_uri(
                    reverse("control:account_set_password", args=[token])
                )
                Mail.send_set_password_email(requested_email, link)
        except Exception:
            logger.warning("Join approval follow-up delivery failed")
            messages.warning(
                request,
                "승인은 완료되었지만 후속 안내 처리가 완료되지 않았습니다.",
            )

        messages.success(request, "승인 완료")
        return redirect("join_requests_pending")

    # 잘못된 action
    messages.error(request, "올바르지 않은 요청입니다.")
    return redirect("join_requests_pending")



# 필요 시 사용할 수 있는 “내 요청 보기”(옵션)
@login_required
def my_join_requests_view(request):
    me_email = (getattr(request.user, "email", None) or getattr(request.user, "username", None) or "").strip().lower()
    items = []
    me = C.get_user_by_email(me_email) if me_email else None
    if me:
        items = C.list_my_join_requests(me["id"])
    return render(request, "control/join_requests_my.html", {"items": items})
