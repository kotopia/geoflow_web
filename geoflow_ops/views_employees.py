from typing import List
from datetime import date
from hashlib import sha256
from django.conf import settings
from django.db import transaction

from django.contrib.auth.decorators import login_required
from django.db import connections
from django.contrib import messages
from django.shortcuts import render, redirect
from django.http import HttpResponseBadRequest, HttpResponseForbidden

from control.services import central_repo as C
from control.middleware import current_db_alias

from control.gf_authz.permissions import gf_perm_required
from control.decorators import require_perm

from django.http import JsonResponse

import re

# -----------------------------
# 로컬 옵션(중앙 이관시, 이 파트를 중앙 조회로 교체)
# -----------------------------

HR_LOCAL_OPTIONS = {
    "position_grade": [
        {"code":"임원", "name":"임원", "ord":10},
        {"code":"부장", "name":"부장", "ord":20},
        {"code":"차장", "name":"차장", "ord":30},
        {"code":"과장", "name":"과장", "ord":40},
        {"code":"대리", "name":"대리", "ord":50},
        {"code":"주임", "name":"주임", "ord":60},
        {"code":"사원", "name":"사원", "ord":70},
        {"code":"인턴", "name":"인턴", "ord":80},
    ],
    "employment_type": [
        {"code":"정규직", "name":"정규직"},
        {"code":"계약직", "name":"계약직"},
        {"code":"파견",   "name":"파견"},
        {"code":"용역",   "name":"용역"},
        {"code":"프리랜서","name":"프리랜서"},
        {"code":"인턴",   "name":"인턴"},
    ],
    "status": [
        {"code":"재직", "name":"재직"},
        {"code":"휴직", "name":"휴직"},
        {"code":"퇴사", "name":"퇴사"},
    ],
}

@require_perm("directory.view")
def hr_options(request, category: str):
    """
    HR 참조 옵션 목록 반환(JSON). 
    - 지금은 로컬 상수에서 반환
    - 추후 중앙(ref.hr_reference + tenant_enabled_values) 조회로 교체
    응답: {results:[{id,text,code,ord},...]}
    """
    items = HR_LOCAL_OPTIONS.get(category, [])
    items = sorted(items, key=lambda x: x.get("ord", 9999))
    return JsonResponse({
        "results": [
            {"id": it["code"], "text": it["name"], "code": it["code"], "ord": it.get("ord", 0)}
            for it in items
        ]
    })


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

def _parse_iso_date(s: str | None):
    s = (s or "").strip()
    if not s:
        return None
    try:
        # 'YYYY-MM-DD' 형식 우선
        return date.fromisoformat(s)
    except ValueError:
        # 'YYYYMMDD' 허용
        if len(s) == 8 and s.isdigit():
            return date(int(s[0:4]), int(s[4:6]), int(s[6:8]))
        return None
    
def _empty_profile():
    return {
        "id": None,
        "email": "",
        "name": "",
        "title": "",
        "phone": "",
        "role_code": "",
        "status": "active",
        "hire_date": None,
        "term_date": None,
        "org_unit_id": "",
        "department_id": "",
        "position_grade": "",
        "emp_type": "",
        "emp_no": "",
        "manager_id": "",
        "rrn_masked": None,
        "central_user_id": None,
    }

# -----------------------------
# Employees List (role_code = 테넌트 기준)
# -----------------------------
@login_required
@require_perm("directory.view")
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
@require_perm("directory.view")
def employees_detail(request, emp_id):
    alias = _alias(request)

    # ------------------------
    # 생성 모드
    # ------------------------
    create_mode = (emp_id == "new")

    if create_mode:
        profile = _empty_profile()
        return render(
            request,
            "geoflow_ops/employees/employee_detail.html",
            {
                "profile": profile,
                "create_mode": True,
                "pending_request": False,
                "org_units": _load_org_units(alias),
                "departments": [],
                "managers": _load_managers(alias),
                "edit_mode": True,  # 신규 생성은 곧바로 편집
            },
        )

    # ------------------------
    # POST: DB에서 직원 업데이트
    # ------------------------
    if request.method == "POST":
        perms = (request.session.get("perms") or [])
        if "directory.edit" not in perms:
            # 계약 상세에서와 동일한 거부 처리 흐름
            return HttpResponseForbidden("Forbidden")
        
        def _nz(v):
            v = (v or "").strip()
            return v if v else None

        title          = _nz(request.POST.get("title"))
        phone          = _nz(request.POST.get("phone"))
        position_grade = _nz(request.POST.get("position_grade"))
        emp_type       = _nz(request.POST.get("emp_type"))
        status         = _nz(request.POST.get("status")) or "재직"   # ★ 기본값 강제
        hire_date      = _nz(request.POST.get("hire_date"))
        term_date      = _nz(request.POST.get("term_date"))
        emp_no         = _nz(request.POST.get("emp_no"))

        org_unit_id    = _nz(request.POST.get("org_unit_id"))
        department_id  = _nz(request.POST.get("department_id"))
        manager_id     = _nz(request.POST.get("manager_id"))

        rrn_plain      = _nz(request.POST.get("rrn_plain"))
        rrn_key        = getattr(settings, "RRN_SYM_KEY", None)

        with connections[alias].cursor() as cur:
            cur.execute("""
                UPDATE hr.employee_profile
                SET title           = %s,
                    phone           = %s,
                    position_grade  = %s,
                    emp_type        = %s,
                    status          = %s,
                    hire_date       = %s::date,
                    term_date       = %s::date,
                    emp_no          = %s,
                    org_unit_id     = NULLIF(%s,'')::uuid,
                    department_id   = NULLIF(%s,'')::uuid,
                    manager_id      = NULLIF(%s,'')::uuid,
                    updated_at      = now()
                WHERE id = %s
            """, [title, phone, position_grade, emp_type, status, hire_date, term_date,
                emp_no, org_unit_id, department_id, manager_id, str(emp_id)])

            rrn_plain = _nz(request.POST.get("rrn_plain"))
            rrn_key   = getattr(settings, "RRN_SYM_KEY", None)

            if rrn_plain:
                digits_only = re.sub(r"\D", "", rrn_plain)
                last4 = digits_only[-4:] if len(digits_only) >= 4 else digits_only
                rrn_hash = sha256(digits_only.encode("utf-8")).digest()

                with connections[alias].cursor() as cur:
                    if rrn_key:
                        cur.execute(
                            """
                            UPDATE hr.employee_profile
                            SET rrn_cipher = pgp_sym_encrypt(%s, %s),
                                rrn_hash   = %s,
                                rrn_last4  = %s
                            WHERE id = %s
                            """,
                            [digits_only, rrn_key, rrn_hash, last4, str(emp_id)]
                        )
                    else:
                        cur.execute(
                            """
                            UPDATE hr.employee_profile
                            SET rrn_cipher = NULL,
                                rrn_hash   = %s,
                                rrn_last4  = %s
                            WHERE id = %s
                            """,
                            [rrn_hash, last4, str(emp_id)]
                        )

        return redirect("tenant:employees_detail", emp_id=emp_id)

    # ------------------------
    # GET: DB에서 직원 조회
    # ------------------------
    with connections[alias].cursor() as cur:
        cur.execute(
            """
            SELECT id::text, email, name, title, role_code, status, phone,
                   hire_date, term_date,
                   org_unit_id::text, department_id::text,
                   position_grade, emp_type, emp_no,
                   manager_id::text, rrn_last4,
                   central_user_id::text
            FROM hr.employee_profile
            WHERE id=%s LIMIT 1
            """, [str(emp_id)]
        )
        row = cur.fetchone()

    if not row:
        messages.error(request, "직원을 찾을 수 없습니다.")
        return redirect("tenant:employees_list")

    profile = {
        "id": row[0],
        "email": row[1] or "",
        "name": row[2] or "",
        "title": row[3] or "",
        "role_code": row[4] or "",
        "status": row[5] or "",
        "phone": row[6] or "",
        "hire_date": row[7],
        "term_date": row[8],
        "org_unit_id": row[9] or "",
        "department_id": row[10] or "",
        "position_grade": row[11] or "",
        "emp_type": row[12] or "",
        "emp_no": row[13] or "",
        "manager_id": row[14] or "",
        "rrn_masked": ("*******-" + row[15]) if row[15] else None,
        "central_user_id": row[16],
    }

    rrn_key = getattr(settings, "RRN_SYM_KEY", None)

    if rrn_key:
        # pgcrypto 필요: CREATE EXTENSION IF NOT EXISTS pgcrypto;
        with connections[alias].cursor() as cur2:
            cur2.execute(
                "SELECT pgp_sym_decrypt(rrn_cipher, %s) FROM hr.employee_profile WHERE id=%s",
                [rrn_key, profile["id"]],
            )
            row = cur2.fetchone()
        rrn_plain = (row[0] or "") if row else ""
        digits = re.sub(r"\D", "", rrn_plain)

        # 원하는 형식: 앞 6자리 + '-' + 7번째 자리 + '******'
        if len(digits) >= 7:
            profile["rrn_masked"] = f"{digits[:6]}-{digits[6]}******"
        else:
            # 복호화 불가·불완전 시 기존 표시 유지(없음)
            profile["rrn_masked"] = profile.get("rrn_masked")  # 템플릿에서 default 처리


    # ------------------------
    # 조직/부서/관리자 옵션 로딩
    # ------------------------
    org_units = _load_org_units(alias)
    departments = _load_departments(alias, profile["org_unit_id"])
    managers = _load_managers(alias)

    employee_roles = _get_employee_roles_for_central(
        request, alias, profile["id"], profile["email"], profile["central_user_id"]
    )
    
    # 편집모드 결정(계약 상세와 동일: ?edit=1 & 편집권한이 있을 때만)
    want_edit = str(request.GET.get("edit", "")).lower() in ("1", "true", "yes")
    perms = (request.session.get("perms") or [])
    edit_mode = bool(want_edit and ("directory.edit" in perms))

    return render(
        request,
        "geoflow_ops/employees/employee_detail.html",
        {
            "profile": profile,
            "create_mode": False,
            "pending_request": False,
            "org_units": org_units,
            "departments": departments,
            "managers": managers,
            "employee_roles": employee_roles,
            "edit_mode": edit_mode,
        },
    )


def _load_org_units(alias):
    with connections[alias].cursor() as cur:
        cur.execute("SELECT id::text, name FROM ops.my_org_units ORDER BY name")
        return [{"id": r[0], "name": r[1]} for r in cur.fetchall()]


def _load_departments(alias, org_unit_id):
    if not org_unit_id:
        return []
    with connections[alias].cursor() as cur:
        cur.execute(
            "SELECT id::text, name FROM hr.departments WHERE org_unit_id=%s ORDER BY name",
            [org_unit_id],
        )
        return [{"id": r[0], "name": r[1]} for r in cur.fetchall()]


def _load_managers(alias):
    with connections[alias].cursor() as cur:
        cur.execute("SELECT id::text, name FROM hr.employee_profile ORDER BY name")
        return [{"id": r[0], "name": r[1]} for r in cur.fetchall()]

# -----------------------------
# Employee Create (간단 생성)
# -----------------------------
@login_required
@require_perm("directory.edit")
def employees_create(request):
    alias = _alias(request)
    _require_role_code_column(alias)

    if request.method == "POST":
        email       = (request.POST.get("email") or "").strip().lower()
        name        = (request.POST.get("name") or request.POST.get("full_name") or "").strip()
        phone       = (request.POST.get("phone") or "").strip()
        title       = (request.POST.get("title") or "").strip()
        role_code   = (request.POST.get("role_code") or "").strip()
        status      = (request.POST.get("status") or "").strip()

        hire_date   = _parse_iso_date(request.POST.get("hire_date"))
        term_date   = _parse_iso_date(request.POST.get("term_date"))

        org_unit_id   = (request.POST.get("org_unit_id") or "").strip()
        department_id = (request.POST.get("department_id") or "").strip()

        position_grade = (request.POST.get("position_grade") or "").strip()
        emp_type       = (request.POST.get("emp_type") or "").strip()
        emp_no         = (request.POST.get("emp_no") or "").strip()

        manager_id   = (request.POST.get("manager_id") or "").strip()

        rrn_plain    = (request.POST.get("rrn_plain") or "").strip()
        rrn_key      = getattr(settings, "RRN_SYM_KEY", None)

        if not email:
            return HttpResponseBadRequest("이메일은 필수입니다.")

        cols = ["email"]
        placeholders = ["%s"]
        params = [email]

        def add(col, val, cast=None):
            if val is None:
                cols.append(col); placeholders.append("NULL")
            elif isinstance(val, str) and val == "":
                cols.append(col); placeholders.append("NULL")
            else:
                cols.append(col)
                if cast == "uuid":
                    placeholders.append("NULLIF(%s,'')::uuid"); params.append(val)
                else:
                    placeholders.append("%s"); params.append(val)

        # 기본/조직/인사
        add("name", name)
        add("phone", phone)
        add("title", title)
        add("role_code", role_code)
        add("status", status)
        add("hire_date", hire_date)
        add("term_date", term_date)
        add("org_unit_id", org_unit_id, cast="uuid")
        add("department_id", department_id, cast="uuid")
        add("position_grade", position_grade)
        add("emp_type", emp_type)
        add("emp_no", emp_no)
        add("manager_id", manager_id, cast="uuid")

        with transaction.atomic(using=alias):
            # 1) INSERT (rrn 제외)
            sql = f"""
                INSERT INTO hr.employee_profile ({", ".join(cols)})
                VALUES ({", ".join(placeholders)})
                RETURNING id::text
            """
            with connections[alias].cursor() as cur:
                cur.execute(sql, params)
                new_id = cur.fetchone()[0]

            # 2) 주민번호 (선택)
            if rrn_plain:
                last4 = rrn_plain[-4:] if len(rrn_plain) >= 4 else rrn_plain
                rrn_hash = sha256(rrn_plain.encode("utf-8")).digest()

                with connections[alias].cursor() as cur:
                    if rrn_key:
                        cur.execute(
                            """
                            UPDATE hr.employee_profile
                               SET rrn_cipher = pgp_sym_encrypt(%s, %s),
                                   rrn_hash   = %s,
                                   rrn_last4  = %s
                             WHERE id = %s
                            """,
                            [rrn_plain, rrn_key, rrn_hash, last4, new_id]
                        )
                    else:
                        cur.execute(
                            """
                            UPDATE hr.employee_profile
                               SET rrn_cipher = NULL,
                                   rrn_hash   = %s,
                                   rrn_last4  = %s
                             WHERE id = %s
                            """,
                            [rrn_hash, last4, new_id]
                        )

        return redirect("tenant:employees_detail", emp_id=new_id)

    # GET: 생성 화면도 동일 템플릿(빈 값) 사용
    return render(
        request,
        "geoflow_ops/employees/employee_detail.html",
        {"profile": {"email": "", "status": "active"}, "create_mode": True, "pending_request": False},
    )

# -----------------------------
# Employee Request Role (권한요청: 테넌트에서 중앙으로 요청)
# -----------------------------
@login_required
@require_perm("directory.roles.assign")
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

def _resolve_and_cache_central_user_id(request, alias: str, emp_id: str, email: str) -> str | None:
    """
    직원 레코드에 central_user_id가 없으면 이메일로 중앙 users.id를 조회하여
    존재 시 employee_profile.central_user_id에 캐시하고 반환한다.
    """
    if not email:
        return None
    central_alias = getattr(settings, "CENTRAL_DB_ALIAS", "default")

    with connections[central_alias].cursor() as cur:
        cur.execute("SELECT id::text FROM users WHERE lower(email)=lower(%s) LIMIT 1", [email])
        row = cur.fetchone()
    if not row:
        return None  # 중앙 미등록(관리용)

    central_user_id = row[0]

    # 캐시(승인된 사용자만 연결된다고 가정)
    with connections[alias].cursor() as cur:
        cur.execute("UPDATE hr.employee_profile SET central_user_id=%s WHERE id=%s AND central_user_id IS NULL",
                    [central_user_id, emp_id])
    return central_user_id

def _get_employee_roles_for_central(request, alias: str, emp_id: str, email: str, central_user_id: str | None) -> list[dict]:
    """
    직원의 중앙 역할 목록을 반환한다.
    1) central_user_id가 있으면 즉시 사용
    2) 없으면 이메일로 users.id를 조회하고, 있으면 캐시 후 사용
    """
    group_id = request.session.get("group_uuid") or request.session.get("group_id")
    if not group_id:
        return []

    user_id = central_user_id
    if not user_id:
        user_id = _resolve_and_cache_central_user_id(request, alias, emp_id, email)
        if not user_id:
            return []  # 중앙 미등록(관리용)

    try:
        return C.list_roles_for_user_in_group(user_id, group_id)  # [{id,name,code}, ...]
    except Exception:
        return []