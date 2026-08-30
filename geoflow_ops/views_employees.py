from __future__ import annotations

from datetime import date
import logging

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import connections, transaction
from django.http import HttpResponseBadRequest, HttpResponseForbidden, JsonResponse
from django.shortcuts import redirect, render

from control.gf_authz.permissions import gf_has_perm, gf_perm_required
from control.services import central_repo as C

from .models import Attachment
from .services.entity_access import require_tenant_context
from .services.s3_service import generate_presigned_get_url

logger = logging.getLogger(__name__)

HR_LOCAL_OPTIONS = {
    "position_grade": [
        {"code": "임원", "name": "임원", "ord": 10},
        {"code": "부장", "name": "부장", "ord": 20},
        {"code": "차장", "name": "차장", "ord": 30},
        {"code": "과장", "name": "과장", "ord": 40},
        {"code": "대리", "name": "대리", "ord": 50},
        {"code": "주임", "name": "주임", "ord": 60},
        {"code": "사원", "name": "사원", "ord": 70},
        {"code": "인턴", "name": "인턴", "ord": 80},
    ],
    "employment_type": [
        {"code": "정규직", "name": "정규직"},
        {"code": "계약직", "name": "계약직"},
        {"code": "파견", "name": "파견"},
        {"code": "용역", "name": "용역"},
        {"code": "프리랜서", "name": "프리랜서"},
        {"code": "인턴", "name": "인턴"},
    ],
    "status": [
        {"code": "재직", "name": "재직"},
        {"code": "휴직", "name": "휴직"},
        {"code": "퇴사", "name": "퇴사"},
    ],
}


def _alias(request):
    return require_tenant_context(request)


def _is_forbidden_central_role(role_code: str) -> bool:
    if not role_code:
        return True
    code = role_code.strip().lower()
    return code.startswith(("central_", "sys_", "super_", "root_")) or code in {
        "central_admin", "system_admin", "super_admin", "owner"
    }


def _require_role_code_column(alias: str) -> None:
    with connections[alias].cursor() as cur:
        cur.execute(
            """
            SELECT 1
              FROM information_schema.columns
             WHERE table_schema='hr'
               AND table_name='employee_profile'
               AND column_name='role_code'
             LIMIT 1
            """
        )
        if cur.fetchone() is None:
            raise RuntimeError("hr.employee_profile.role_code column is required")


def _parse_iso_date(value: str | None):
    value = (value or "").strip()
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        if len(value) == 8 and value.isdigit():
            try:
                return date(int(value[0:4]), int(value[4:6]), int(value[6:8]))
            except ValueError:
                return None
        return None


def _empty_profile():
    return {
        "id": None, "email": "", "name": "", "title": "", "phone": "",
        "role_code": "", "status": "재직", "hire_date": None, "term_date": None,
        "org_unit_id": "", "department_id": "", "position_grade": "",
        "emp_type": "", "emp_no": "", "manager_id": "", "central_user_id": None,
    }


def _reject_rrn_input(request):
    if (request.POST.get("rrn_plain") or "").strip():
        return HttpResponseBadRequest("주민등록번호는 GeoFlow에서 수집하지 않습니다.")
    return None


def _load_org_units(alias):
    with connections[alias].cursor() as cur:
        cur.execute("SELECT id::text, name FROM ops.my_org_units ORDER BY name")
        return [{"id": row[0], "name": row[1]} for row in cur.fetchall()]


def _load_departments(alias, org_unit_id):
    if not org_unit_id:
        return []
    with connections[alias].cursor() as cur:
        cur.execute(
            "SELECT id::text, name FROM hr.departments WHERE org_unit_id=%s ORDER BY name",
            [org_unit_id],
        )
        return [{"id": row[0], "name": row[1]} for row in cur.fetchall()]


def _load_managers(alias):
    with connections[alias].cursor() as cur:
        cur.execute(
            "SELECT id::text, name FROM hr.employee_profile WHERE is_deleted=false ORDER BY name"
        )
        return [{"id": row[0], "name": row[1]} for row in cur.fetchall()]


def _resolve_and_cache_central_user_id(request, alias: str, emp_id: str, email: str):
    if not email:
        return None
    central_alias = getattr(settings, "CENTRAL_DB_ALIAS", "default")
    with connections[central_alias].cursor() as cur:
        cur.execute("SELECT id::text FROM users WHERE lower(email)=lower(%s) LIMIT 1", [email])
        row = cur.fetchone()
    if not row:
        return None
    user_id = row[0]
    with connections[alias].cursor() as cur:
        cur.execute(
            "UPDATE hr.employee_profile SET central_user_id=%s WHERE id=%s AND central_user_id IS NULL",
            [user_id, emp_id],
        )
    return user_id


def _get_employee_roles_for_central(request, alias: str, emp_id: str, email: str, central_user_id: str | None):
    group_id = request.session.get("group_uuid") or request.session.get("group_id")
    if not group_id:
        return []
    user_id = central_user_id or _resolve_and_cache_central_user_id(request, alias, emp_id, email)
    if not user_id:
        return []
    try:
        return C.list_roles_for_user_in_group(user_id, group_id)
    except Exception:
        logger.warning("employee central role lookup failed")
        return []


@login_required
@gf_perm_required("directory.view")
def hr_options(request, category: str):
    _alias(request)
    items = sorted(HR_LOCAL_OPTIONS.get(category, []), key=lambda item: item.get("ord", 9999))
    return JsonResponse({"results": [
        {"id": item["code"], "text": item["name"], "code": item["code"], "ord": item.get("ord", 0)}
        for item in items
    ]})


@login_required
@gf_perm_required("directory.view")
def employees_list(request):
    alias = _alias(request)
    with connections[alias].cursor() as cur:
        cur.execute(
            "SELECT id::text, email, name, title, role_code, status, phone FROM hr.employee_profile ORDER BY name"
        )
        rows = cur.fetchall()
    employees = [{
        "id": row[0], "email": row[1], "name": row[2], "title": row[3],
        "role_code": row[4], "status": row[5], "phone": row[6],
    } for row in rows]
    return render(request, "geoflow_ops/employees/employee_list.html", {"employees": employees})


@login_required
@gf_perm_required("directory.view")
def employees_detail(request, emp_id):
    alias = _alias(request)
    if request.method == "POST":
        if not gf_has_perm(request, "directory.edit"):
            return HttpResponseForbidden("Forbidden")
        rejected = _reject_rrn_input(request)
        if rejected:
            return rejected

        def optional(name):
            value = (request.POST.get(name) or "").strip()
            return value or None

        values = [
            optional("title"), optional("phone"), optional("position_grade"),
            optional("emp_type"), optional("status") or "재직", optional("hire_date"),
            optional("term_date"), optional("emp_no"), optional("org_unit_id"),
            optional("department_id"), optional("manager_id"), str(emp_id),
        ]
        with connections[alias].cursor() as cur:
            cur.execute(
                """
                UPDATE hr.employee_profile
                   SET title = %s,
                       phone = %s,
                       position_grade = %s,
                       emp_type = %s,
                       status = %s,
                       hire_date = %s::date,
                       term_date = %s::date,
                       emp_no = %s,
                       org_unit_id = NULLIF(%s,'')::uuid,
                       department_id = NULLIF(%s,'')::uuid,
                       manager_id = NULLIF(%s,'')::uuid,
                       updated_at = now()
                 WHERE id = %s
                """,
                values,
            )
        return redirect("tenant:employees_detail", emp_id=emp_id)

    with connections[alias].cursor() as cur:
        cur.execute(
            """
            SELECT id::text, email, name, title, role_code, status, phone,
                   hire_date, term_date, org_unit_id::text, department_id::text,
                   position_grade, emp_type, emp_no, manager_id::text, central_user_id::text
              FROM hr.employee_profile
             WHERE id=%s LIMIT 1
            """,
            [str(emp_id)],
        )
        row = cur.fetchone()
    if not row:
        messages.error(request, "직원을 찾을 수 없습니다.")
        return redirect("tenant:employees_list")

    profile = {
        "id": row[0], "email": row[1] or "", "name": row[2] or "", "title": row[3] or "",
        "role_code": row[4] or "", "status": row[5] or "", "phone": row[6] or "",
        "hire_date": row[7], "term_date": row[8], "org_unit_id": row[9] or "",
        "department_id": row[10] or "", "position_grade": row[11] or "",
        "emp_type": row[12] or "", "emp_no": row[13] or "", "manager_id": row[14] or "",
        "central_user_id": row[15],
    }

    org_units = _load_org_units(alias)
    departments = _load_departments(alias, profile["org_unit_id"])
    managers = _load_managers(alias)
    employee_roles = _get_employee_roles_for_central(
        request, alias, profile["id"], profile["email"], profile["central_user_id"]
    )

    photo_attachment = (
        Attachment.objects.using(alias)
        .filter(entity_type="employee", entity_id=profile["id"], purpose__in=["photo_thumb", "thumb"], active=True, deleted_at__isnull=True)
        .order_by("ord", "-created_at").first()
    )
    if not photo_attachment:
        photo_attachment = (
            Attachment.objects.using(alias)
            .filter(entity_type="employee", entity_id=profile["id"], purpose="photo", active=True, deleted_at__isnull=True)
            .order_by("ord", "-created_at").first()
        )

    photo_url = None
    if photo_attachment:
        try:
            photo_url = generate_presigned_get_url(photo_attachment.object_key, expires_in=3600)
        except Exception:
            logger.warning("employee photo presign failed")

    doc_attachment = (
        Attachment.objects.using(alias)
        .filter(entity_type="employee", entity_id=profile["id"], purpose="doc", active=True, deleted_at__isnull=True)
        .order_by("ord", "-created_at").first()
    )
    wants_edit = str(request.GET.get("edit", "")).lower() in {"1", "true", "yes"}
    edit_mode = bool(wants_edit and gf_has_perm(request, "directory.edit"))
    return render(request, "geoflow_ops/employees/employee_detail.html", {
        "profile": profile, "create_mode": False, "pending_request": False,
        "org_units": org_units, "departments": departments, "managers": managers,
        "employee_roles": employee_roles, "edit_mode": edit_mode,
        "photo_attachment": photo_attachment, "photo_url": photo_url,
        "doc_attachment": doc_attachment,
    })


@login_required
@gf_perm_required("directory.edit")
def employees_create(request):
    alias = _alias(request)
    _require_role_code_column(alias)
    if request.method == "POST":
        rejected = _reject_rrn_input(request)
        if rejected:
            return rejected
        email = (request.POST.get("email") or "").strip().lower()
        if not email:
            return HttpResponseBadRequest("이메일은 필수입니다.")
        fields = {
            "name": (request.POST.get("name") or request.POST.get("full_name") or "").strip(),
            "phone": (request.POST.get("phone") or "").strip(),
            "title": (request.POST.get("title") or "").strip(),
            "role_code": (request.POST.get("role_code") or "").strip(),
            "status": (request.POST.get("status") or "재직").strip(),
            "hire_date": _parse_iso_date(request.POST.get("hire_date")),
            "term_date": _parse_iso_date(request.POST.get("term_date")),
            "org_unit_id": (request.POST.get("org_unit_id") or "").strip(),
            "department_id": (request.POST.get("department_id") or "").strip(),
            "position_grade": (request.POST.get("position_grade") or "").strip(),
            "emp_type": (request.POST.get("emp_type") or "").strip(),
            "emp_no": (request.POST.get("emp_no") or "").strip(),
            "manager_id": (request.POST.get("manager_id") or "").strip(),
        }
        cols = ["email"]
        placeholders = ["%s"]
        params = [email]

        def add(column, value, *, uuid_value=False):
            cols.append(column)
            if value in (None, ""):
                placeholders.append("NULL")
            elif uuid_value:
                placeholders.append("NULLIF(%s,'')::uuid")
                params.append(value)
            else:
                placeholders.append("%s")
                params.append(value)

        for key in ("name", "phone", "title", "role_code", "status", "hire_date", "term_date"):
            add(key, fields[key])
        add("org_unit_id", fields["org_unit_id"], uuid_value=True)
        add("department_id", fields["department_id"], uuid_value=True)
        for key in ("position_grade", "emp_type", "emp_no"):
            add(key, fields[key])
        add("manager_id", fields["manager_id"], uuid_value=True)

        with transaction.atomic(using=alias):
            with connections[alias].cursor() as cur:
                cur.execute(
                    f"INSERT INTO hr.employee_profile ({', '.join(cols)}) VALUES ({', '.join(placeholders)}) RETURNING id::text",
                    params,
                )
                new_id = cur.fetchone()[0]
        return redirect("tenant:employees_detail", emp_id=new_id)

    profile = _empty_profile()
    return render(request, "geoflow_ops/employees/employee_detail.html", {
        "profile": profile, "create_mode": True, "pending_request": False,
        "org_units": _load_org_units(alias), "departments": [], "managers": _load_managers(alias),
        "employee_roles": [], "edit_mode": True, "photo_attachment": None,
        "photo_url": None, "doc_attachment": None,
    })
