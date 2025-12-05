from typing import List
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.db import connections
from django.contrib import messages
from django.shortcuts import render, redirect
from django.http import HttpResponseBadRequest

from control.services import central_repo as C
from control.middleware import current_db_alias

from control.gf_authz.permissions import gf_perm_required


# -----------------------------
# Helpers
# -----------------------------
def _alias(request):
    return current_db_alias()

def _is_forbidden_central_role(role_code: str) -> bool:
    """테넌트가 요청해서는 안 되는 중앙/시스템 권한 필터"""
    if not role_code:
        return True
    rc = role_code.strip().lower()
    forbidden_prefixes = ("central_", "sys_", "super_", "root_")
    forbidden_exact = {"central_admin", "system_admin", "super_admin", "owner"}
    return rc.startswith(forbidden_prefixes) or rc in forbidden_exact

def _require_role_code_column(alias: str) -> None:
    """테넌트에 role_code가 없으면 명확한 에러 메시지로 안내"""
    with connections[alias].cursor() as cur:
        cur.execute("""
            SELECT 1
              FROM information_schema.columns
             WHERE table_schema='hr' AND table_name='employee_profile' AND column_name='role_code'
             LIMIT 1
        """)
        if cur.fetchone() is None:
            raise RuntimeError(
                "hr.employee_profile.role_code 컬럼이 없습니다. "
                "테넌트 권한은 role_code를 기준으로 하므로 컬럼을 추가하세요."
            )

# -----------------------------
# Employees List (role_code = 테넌트 기준)
# -----------------------------
@login_required
@gf_perm_required("directory.view")
def employees_list(request):
    alias = _alias(request)
    with connections[alias].cursor() as cur:
        cur.execute("SELECT id::text, email, name, title, role_code, status, phone FROM hr.employee_profile ORDER BY name")
        rows = cur.fetchall()

    employees = [{
        "id": r[0], "email": r[1], "name": r[2], "title": r[3],
        "role_code": r[4], "status": r[5], "phone": r[6],
    } for r in rows]

    return render(request, "geoflow_ops/employees/employee_list.html", {"employees": employees})

# -----------------------------
# Employee Detail (role_code = 테넌트 기준)
# -----------------------------
@login_required
@gf_perm_required("directory.view")
def employees_detail(request, emp_id):
    alias = _alias(request)
    with connections[alias].cursor() as cur:
        cur.execute("SELECT id::text, email, name, title, role_code, status, phone FROM hr.employee_profile WHERE id=%s LIMIT 1", [str(emp_id)])
        row = cur.fetchone()

    if not row:
        messages.error(request, "직원을 찾을 수 없습니다.")
        return redirect("employees_list")

    profile = {
        "id": row[0], "email": row[1], "name": row[2], "title": row[3],
        "role_code": row[4], "status": row[5], "phone": row[6],
    }

    return render(request, "geoflow_ops/employees/employee_detail.html", {
        "profile": profile,
        # (선택) pending_request 계산 로직 필요시 중앙 join_requests를 조회해 표시
        "pending_request": False,
    })

# -----------------------------
# Employee Create (간단 생성)
# -----------------------------
@login_required
@gf_perm_required("directory.invite")
def employees_create(request):
    alias = _alias(request)
    _require_role_code_column(alias)

    if request.method == "POST":
        email = (request.POST.get("email") or "").strip().lower()
        name_or_full = (request.POST.get("name") or request.POST.get("full_name") or "").strip()
        title = (request.POST.get("title") or "").strip()
        phone = (request.POST.get("phone") or "").strip()
        role_code = (request.POST.get("role_code") or "").strip()  # 선택 입력 가능

        if not email:
            return HttpResponseBadRequest("이메일은 필수입니다.")

        # 최소 필드 insert
        cols: List[str] = ["email"]
        placeholders: List[str] = ["%s"]
        params: List[str] = [email]

        for col, val in (("name", name_or_full), ("title", title), ("phone", phone), ("role_code", role_code)):
            if val:
                cols.append(col); placeholders.append("%s"); params.append(val)

        sql = f"""
            INSERT INTO hr.employee_profile ({", ".join(cols)})
            VALUES ({", ".join(placeholders)})
            RETURNING id::text
        """
        with connections[alias].cursor() as cur:
            cur.execute(sql, params)
            new_id = cur.fetchone()[0]

        return redirect("tenant:employees_detail", emp_id=new_id)

    return render(request, "geoflow_ops/employees/employee_create.html")

# -----------------------------
# Employee Request Role (권한요청: 테넌트에서 중앙으로 요청)
# -----------------------------
@login_required
@gf_perm_required("directory.roles.assign")
def employees_request_role(request, emp_id):
    alias = _alias(request)
    _require_role_code_column(alias)

    # 대상 직원 기본 정보
    with connections[alias].cursor() as cur:
        cur.execute("SELECT email, name FROM hr.employee_profile WHERE id=%s LIMIT 1", [str(emp_id)])
        row = cur.fetchone()
    if not row:
        messages.error(request, "직원을 찾을 수 없습니다.")
        return redirect("employees_list")
    target_email = (row[0] or "").strip().lower()
    target_name = row[1] or ""

    if request.method == "GET":
        # 중앙 역할 목록(활성 + 테넌트에서 금지된 중앙/시스템 권한은 필터)
        roles = C.list_active_roles()
        role_codes = [r["code"] for r in roles if not _is_forbidden_central_role(r["code"])]
        return render(
            request,
            "geoflow_ops/employees/employee_request_role.html",
            {
                "emp_id": emp_id,
                "employee_email": target_email,
                "employee_name": target_name,
                "role_codes": role_codes,
            },
        )

    # POST: 중앙에 join_requests UPSERT
    me_email = (getattr(request.user, "email", None) or getattr(request.user, "username", None) or "").strip().lower()
    my_user_id = C.get_or_create_user_by_email(me_email)

    group_uuid = request.session.get("group_uuid") or request.session.get("group_id")
    role_code = (request.POST.get("role_code") or "").strip()

    if not group_uuid or not role_code:
        messages.error(request, "그룹 또는 역할이 누락되었습니다.")
        return redirect("tenant:employees_detail", emp_id=emp_id)

    if _is_forbidden_central_role(role_code):
        messages.error(request, "해당 역할은 테넌트에서 요청할 수 없습니다.")
        return redirect("tenant:employees_detail", emp_id=emp_id)

    # 역할 코드 유효성(중앙 roles 존재 여부) 확인
    if not C.get_role_id_by_code(role_code):
        messages.error(request, f"유효하지 않은 역할 코드입니다: {role_code}")
        return redirect("tenant:employees_detail", emp_id=emp_id)

    # 중앙에 요청 등록/갱신
    C.add_or_update_join_request(
        user_id=my_user_id,
        group_id=group_uuid,
        requested_email=target_email,
        role_code=role_code,
    )

    messages.success(request, "권한 요청이 접수되었습니다.")
    return redirect("tenant:employees_detail", emp_id=emp_id)
