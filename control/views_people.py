from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from control.decorators import require_perm
from control.models import UserGroupMap, Role
from control.services_people import get_group_alias, ensure_group_profile, ensure_profile, fetch_profile, list_members
from control.services_identity import to_group_uuid, get_or_create_user_by_email, create_or_pending_membership
from control.middleware import get_current_tenant
from django.http import HttpResponseRedirect
from django.urls import reverse
from django.contrib import messages
from django.views.decorators.csrf import csrf_protect
from django.db import connections

@login_required
@require_perm("people.view")
def people_list(request):
    gid_raw = get_current_tenant()
    gid = to_group_uuid(gid_raw)  # UUID 정규화
    if not gid:
        return HttpResponseRedirect(reverse('post_login_redirect'))

    alias = get_group_alias(gid)
    members = list_members(gid, alias)  # ← 템플릿 형식에 맞는 dict 리스트 반환

    return render(request, "webgisapp/people_list.html", {"members": members})

@login_required
@require_perm('people.view')
def people_detail(request, user_id):
    gid = request.session.get("group_id")  # 중앙 UUID
    alias = get_group_alias(gid)

    # 1) 그룹 DB에 row가 없으면 생성
    ensure_group_profile(user_id, gid)

    # 2) 중앙 users에서 이메일만 조회 (display_name 제거)
    with connections["default"].cursor() as cur:
        cur.execute("SELECT email FROM users WHERE id=%s", [user_id])
        row = cur.fetchone()
    email = row[0] if row else None
    name  = None  # 중앙에 이름 컬럼이 없으므로 None

    # 3) 이메일 동기화(업서트)
    if email:
        ensure_profile(alias, user_id, email, name)

    # 4) 테넌트 프로필 조회
    prof = fetch_profile(alias, user_id) or {
        "email": email, "name": name, "phone": None,
        "hire_date": None, "title": None, "status": "active",
    }

    return render(request, "webgisapp/people_detail.html", {"profile": prof})

@require_perm("people.manage")
def change_role(request, user_id):
    gid = get_current_tenant()
    if request.method == "POST":
        role_code = request.POST.get("role_code")
        role = get_object_or_404(Role.objects.using("default"), code=role_code)
        ugm = get_object_or_404(UserGroupMap.objects.using("default"),
                                user_id=user_id, group_id=gid)
        ugm.role_id = role.id
        ugm.save(using="default", update_fields=["role_id"])
        return redirect("people_detail", user_id=user_id)
    roles = Role.objects.using("default").all()
    return render(request, "webgisapp/people_change_role.html", {"roles": roles})

# control/views_people.py (맨 아래 임시)
from django.http import HttpResponse
def invite(request):
    return HttpResponse("초대기능은 추후 구현 예정입니다.", content_type="text/plain")

def _parse_emails(raw: str):
    return [e.strip().lower() for e in (raw or "").replace(";", ",").split(",") if e.strip()]

def _get_role_id(code: str):
    with connections["default"].cursor() as cur:
        cur.execute("SELECT id FROM roles WHERE code=%s LIMIT 1", [code])
        row = cur.fetchone()
    return row[0] if row else None

@require_perm("people.manage")
@csrf_protect
def people_invite(request):
    gid = to_group_uuid(get_current_tenant())

    if request.method == "POST":
        emails = _parse_emails(request.POST.get("emails"))
        if not emails:
            messages.error(request, "이메일을 1개 이상 입력하세요.")
            return render(request, "webgisapp/people_invite.html")

        viewer_role_id = _get_role_id("viewer")
        if not viewer_role_id:
            messages.error(request, "역할(viewer)이 준비되지 않았습니다.")
            return render(request, "webgisapp/people_invite.html")

        auto, pend = 0, 0
        for email in emails:
            user_id, _ = get_or_create_user_by_email(email)  # 중앙 users stub upsert
            result = create_or_pending_membership(user_id, gid, viewer_role_id)
            auto += (result == "auto_approved")
            pend += (result == "pending")

        if auto:
            messages.success(request, f"자동 승인 {auto}명(viewer).")
        if pend:
            messages.info(request, f"승인 대기 {pend}명은 ‘대기 중 합류 요청’에서 처리하세요.")
        return redirect("people_list")

    return render(request, "webgisapp/people_invite.html")