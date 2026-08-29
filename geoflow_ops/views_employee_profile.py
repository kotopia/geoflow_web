from __future__ import annotations

from datetime import date
import logging

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db import connections, transaction
from django.http import HttpResponseBadRequest, JsonResponse
from django.shortcuts import redirect, render

from .models import Attachment
from .services.employee_access import employee_access_policy
from .services.entity_access import require_tenant_context
from .services.s3_service import generate_presigned_get_url
from .views_employees import (
    HR_LOCAL_OPTIONS,
    _get_employee_roles_for_central,
    _load_departments,
    _load_managers,
    _load_org_units,
    _parse_iso_date,
    _reject_rrn_input,
    _require_role_code_column,
)

logger = logging.getLogger(__name__)

OPTION_SYSTEM_KEYS = {
    "position_grade": "hr.position_grade",
    "position_title": "hr.position_title",
    "employment_type": "hr.employment_type",
    "status": "hr.status",
    "technical_grade": "hr.technical_grade",
}


def _table_exists(alias: str, relation: str) -> bool:
    with connections[alias].cursor() as cur:
        cur.execute("SELECT to_regclass(%s) IS NOT NULL", [relation])
        row = cur.fetchone()
    return bool(row and row[0])


def _settings_options(alias: str, category: str):
    system_key = OPTION_SYSTEM_KEYS.get(category)
    if system_key and _table_exists(alias, "ops.settings_nodes"):
        with connections[alias].cursor() as cur:
            cur.execute(
                """
                SELECT child.code, child.name, child.ord
                  FROM ops.settings_nodes category
                  JOIN ops.settings_nodes child ON child.parent_id = category.id
                 WHERE category.system_key = %s
                   AND category.active = true
                   AND child.active = true
                 ORDER BY child.ord, child.name, child.code
                """,
                [system_key],
            )
            rows = cur.fetchall()
        if rows:
            return [
                {"code": row[0] or "", "name": row[1] or row[0] or "", "ord": row[2] or 0}
                for row in rows
            ]
    return sorted(HR_LOCAL_OPTIONS.get(category, []), key=lambda item: item.get("ord", 9999))


def hr_options(request, category: str):
    alias = require_tenant_context(request)
    items = _settings_options(alias, category)
    return JsonResponse({
        "results": [
            {"id": item["code"], "text": item["name"], "code": item["code"], "ord": item.get("ord", 0)}
            for item in items
        ]
    })


def _fetch_profile(alias: str, emp_id):
    with connections[alias].cursor() as cur:
        cur.execute(
            """
            SELECT id::text, email, name, title, role_code, status, phone,
                   hire_date, term_date, org_unit_id::text, department_id::text,
                   position_grade, emp_type, emp_no, manager_id::text, central_user_id::text,
                   addr_road, addr_detail, addr_zip
              FROM hr.employee_profile
             WHERE id=%s LIMIT 1
            """,
            [str(emp_id)],
        )
        row = cur.fetchone()
    if not row:
        return None
    return {
        "id": row[0], "email": row[1] or "", "name": row[2] or "", "title": row[3] or "",
        "role_code": row[4] or "", "status": row[5] or "", "phone": row[6] or "",
        "hire_date": row[7], "term_date": row[8], "org_unit_id": row[9] or "",
        "department_id": row[10] or "", "position_grade": row[11] or "",
        "emp_type": row[12] or "", "emp_no": row[13] or "", "manager_id": row[14] or "",
        "central_user_id": row[15], "addr_road": row[16] or "",
        "addr_detail": row[17] or "", "addr_zip": row[18] or "",
    }


def _empty_profile():
    return {
        "id": None, "email": "", "name": "", "title": "", "role_code": "",
        "status": "재직", "phone": "", "hire_date": None, "term_date": None,
        "org_unit_id": "", "department_id": "", "position_grade": "", "emp_type": "",
        "emp_no": "", "manager_id": "", "central_user_id": None,
        "addr_road": "", "addr_detail": "", "addr_zip": "",
    }


def employees_list(request):
    alias = require_tenant_context(request)
    policy = employee_access_policy(request, alias)
    if not policy.can_list:
        if policy.self_employee_id:
            return redirect("tenant:employees_detail", emp_id=policy.self_employee_id)
        raise PermissionDenied("Employee profile is not linked to this login.")
    with connections[alias].cursor() as cur:
        cur.execute(
            """
            SELECT id::text, email, name, title, role_code, status, phone,
                   position_grade, emp_no
              FROM hr.employee_profile
             ORDER BY name, email
            """
        )
        rows = cur.fetchall()
    employees = [
        {
            "id": row[0], "email": row[1] or "", "name": row[2] or "",
            "title": row[3] or "", "role_code": row[4] or "", "status": row[5] or "",
            "phone": row[6] or "", "position_grade": row[7] or "", "emp_no": row[8] or "",
        }
        for row in rows
    ]
    return render(
        request,
        "geoflow_ops/employees/employee_list.html",
        {"employees": employees, "employee_access": policy},
    )


def employee_me(request):
    alias = require_tenant_context(request)
    policy = employee_access_policy(request, alias)
    if not policy.self_employee_id:
        messages.error(request, "로그인 계정과 연결된 직원 정보가 없습니다.")
        if policy.can_list:
            return redirect("tenant:employees_list")
        raise PermissionDenied("Employee profile is not linked to this login.")
    return redirect("tenant:employees_detail", emp_id=policy.self_employee_id)


def _history_rows(alias: str, table: str, columns: str, emp_id):
    if not _table_exists(alias, table):
        return []
    with connections[alias].cursor() as cur:
        cur.execute(
            f"SELECT {columns} FROM {table} WHERE employee_id=%s AND active=true ORDER BY ord, created_at",
            [str(emp_id)],
        )
        return cur.fetchall()


def _employee_history(alias: str, emp_id):
    education = [
        {
            "id": row[0], "school_name": row[1] or "", "school_type": row[2] or "",
            "degree": row[3] or "", "major": row[4] or "", "admission_date": row[5],
            "graduation_date": row[6], "education_status": row[7] or "", "note": row[8] or "",
        }
        for row in _history_rows(
            alias,
            "hr.employee_education",
            "id::text, school_name, school_type, degree, major, admission_date, graduation_date, education_status, note",
            emp_id,
        )
    ]
    qualifications = [
        {
            "id": row[0], "qualification_name": row[1] or "", "issuer": row[2] or "",
            "license_no": row[3] or "", "acquired_date": row[4], "expiry_date": row[5],
            "note": row[6] or "",
        }
        for row in _history_rows(
            alias,
            "hr.employee_qualification",
            "id::text, qualification_name, issuer, license_no, acquired_date, expiry_date, note",
            emp_id,
        )
    ]
    technical_grades = [
        {
            "id": row[0], "field_name": row[1] or "", "grade_code": row[2] or "",
            "recognized_date": row[3], "issuer": row[4] or "", "note": row[5] or "",
        }
        for row in _history_rows(
            alias,
            "hr.employee_technical_grade",
            "id::text, field_name, grade_code, recognized_date, issuer, note",
            emp_id,
        )
    ]
    careers = [
        {
            "id": row[0], "company_name": row[1] or "", "department": row[2] or "",
            "position_title": row[3] or "", "started_on": row[4], "ended_on": row[5],
            "duties": row[6] or "", "note": row[7] or "",
        }
        for row in _history_rows(
            alias,
            "hr.employee_career",
            "id::text, company_name, department, position_title, started_on, ended_on, duties, note",
            emp_id,
        )
    ]
    return education, qualifications, technical_grades, careers


def _optional(request, name):
    value = str(request.POST.get(name) or "").strip()
    return value or None


def _save_profile(request, alias: str, profile, policy):
    if not policy.can_edit(profile["id"]):
        raise PermissionDenied("Permission denied")
    rejected = _reject_rrn_input(request)
    if rejected:
        return rejected

    if policy.can_edit_admin_fields(profile["id"]):
        values = [
            _optional(request, "name"), _optional(request, "phone"), _optional(request, "title"),
            _optional(request, "position_grade"), _optional(request, "emp_type"),
            _optional(request, "status") or "재직", _optional(request, "hire_date"),
            _optional(request, "term_date"), _optional(request, "emp_no"),
            _optional(request, "org_unit_id"), _optional(request, "department_id"),
            _optional(request, "manager_id"), _optional(request, "addr_road"),
            _optional(request, "addr_detail"), _optional(request, "addr_zip"),
            str(profile["id"]),
        ]
        with connections[alias].cursor() as cur:
            cur.execute(
                """
                UPDATE hr.employee_profile
                   SET name=%s, phone=%s, title=%s, position_grade=%s, emp_type=%s,
                       status=%s, hire_date=%s::date, term_date=%s::date, emp_no=%s,
                       org_unit_id=NULLIF(%s,'')::uuid,
                       department_id=NULLIF(%s,'')::uuid,
                       manager_id=NULLIF(%s,'')::uuid,
                       addr_road=%s, addr_detail=%s, addr_zip=%s,
                       updated_at=now()
                 WHERE id=%s
                """,
                values,
            )
    else:
        with connections[alias].cursor() as cur:
            cur.execute(
                """
                UPDATE hr.employee_profile
                   SET name=%s, phone=%s, addr_road=%s, addr_detail=%s, addr_zip=%s,
                       updated_at=now()
                 WHERE id=%s
                """,
                [
                    _optional(request, "name"), _optional(request, "phone"),
                    _optional(request, "addr_road"), _optional(request, "addr_detail"),
                    _optional(request, "addr_zip"), str(profile["id"]),
                ],
            )
    messages.success(request, "직원 정보를 저장했습니다.")
    return redirect("tenant:employees_detail", emp_id=profile["id"])


HISTORY_SECTIONS = {
    "education": {
        "table": "hr.employee_education",
        "required": "school_name",
        "fields": (
            ("school_name", "text"), ("school_type", "text"), ("degree", "text"),
            ("major", "text"), ("admission_date", "date"), ("graduation_date", "date"),
            ("education_status", "text"), ("note", "text"),
        ),
    },
    "qualification": {
        "table": "hr.employee_qualification",
        "required": "qualification_name",
        "fields": (
            ("qualification_name", "text"), ("issuer", "text"), ("license_no", "text"),
            ("acquired_date", "date"), ("expiry_date", "date"), ("note", "text"),
        ),
    },
    "technical_grade": {
        "table": "hr.employee_technical_grade",
        "required": "grade_code",
        "fields": (
            ("field_name", "text"), ("grade_code", "text"), ("recognized_date", "date"),
            ("issuer", "text"), ("note", "text"),
        ),
    },
    "career": {
        "table": "hr.employee_career",
        "required": "company_name",
        "fields": (
            ("company_name", "text"), ("department", "text"), ("position_title", "text"),
            ("started_on", "date"), ("ended_on", "date"), ("duties", "text"), ("note", "text"),
        ),
    },
}


def _save_history(request, alias: str, emp_id, policy, section: str):
    if not policy.can_edit(emp_id):
        raise PermissionDenied("Permission denied")
    config = HISTORY_SECTIONS.get(section)
    if not config or not _table_exists(alias, config["table"]):
        return HttpResponseBadRequest("지원하지 않는 직원 이력 구분입니다.")

    record_id = str(request.POST.get("record_id") or "").strip() or None
    action = str(request.POST.get("action") or "save").strip().lower()
    if action == "archive":
        if not record_id:
            return HttpResponseBadRequest("이력 ID가 필요합니다.")
        with connections[alias].cursor() as cur:
            cur.execute(
                f"UPDATE {config['table']} SET active=false, updated_at=now() WHERE id=%s AND employee_id=%s",
                [record_id, str(emp_id)],
            )
        messages.success(request, "이력 항목을 숨김 처리했습니다.")
        return redirect("tenant:employees_detail", emp_id=emp_id)

    required_value = _optional(request, config["required"])
    if not required_value:
        return HttpResponseBadRequest("필수 항목을 입력하세요.")

    columns = []
    values = []
    assignments = []
    for field, field_type in config["fields"]:
        columns.append(field)
        value = _optional(request, field)
        if field_type == "date" and value:
            parsed = _parse_iso_date(value)
            value = parsed.isoformat() if parsed else None
        values.append(value)
        assignments.append(f"{field}=%s" + ("::date" if field_type == "date" else ""))

    with connections[alias].cursor() as cur:
        if record_id:
            cur.execute(
                f"UPDATE {config['table']} SET {', '.join(assignments)}, active=true, updated_at=now() WHERE id=%s AND employee_id=%s",
                [*values, record_id, str(emp_id)],
            )
        else:
            placeholders = ["%s::date" if field_type == "date" else "%s" for _, field_type in config["fields"]]
            cur.execute(
                f"INSERT INTO {config['table']} (employee_id, {', '.join(columns)}) VALUES (%s, {', '.join(placeholders)})",
                [str(emp_id), *values],
            )
    messages.success(request, "직원 이력을 저장했습니다.")
    return redirect("tenant:employees_detail", emp_id=emp_id)


def employees_detail(request, emp_id):
    alias = require_tenant_context(request)
    policy = employee_access_policy(request, alias)
    profile = _fetch_profile(alias, emp_id)
    if not profile:
        messages.error(request, "직원을 찾을 수 없습니다.")
        return redirect("tenant:employees_me" if not policy.can_list else "tenant:employees_list")
    if not policy.can_view(profile["id"]):
        raise PermissionDenied("Permission denied")

    if request.method == "POST":
        section = str(request.POST.get("section") or "profile").strip().lower()
        if section == "profile":
            return _save_profile(request, alias, profile, policy)
        return _save_history(request, alias, profile["id"], policy, section)

    org_units = _load_org_units(alias)
    departments = _load_departments(alias, profile["org_unit_id"])
    managers = _load_managers(alias)
    employee_roles = (
        _get_employee_roles_for_central(
            request, alias, profile["id"], profile["email"], profile["central_user_id"]
        )
        if policy.can_view(profile["id"])
        else []
    )

    photo_attachment = (
        Attachment.objects.using(alias)
        .filter(
            entity_type="employee",
            entity_id=profile["id"],
            purpose__in=["photo_thumb", "thumb"],
            active=True,
            deleted_at__isnull=True,
        )
        .order_by("ord", "-created_at")
        .first()
    )
    if not photo_attachment:
        photo_attachment = (
            Attachment.objects.using(alias)
            .filter(entity_type="employee", entity_id=profile["id"], purpose="photo", active=True, deleted_at__isnull=True)
            .order_by("ord", "-created_at")
            .first()
        )
    photo_url = None
    if photo_attachment:
        try:
            photo_url = generate_presigned_get_url(photo_attachment.object_key, expires_in=3600)
        except Exception:
            logger.warning("employee photo presign failed")

    doc_attachments = list(
        Attachment.objects.using(alias)
        .filter(entity_type="employee", entity_id=profile["id"], purpose="doc", active=True, deleted_at__isnull=True)
        .order_by("ord", "-created_at")
    )
    education, qualifications, technical_grades, careers = _employee_history(alias, profile["id"])
    wants_edit = str(request.GET.get("edit", "")).lower() in {"1", "true", "yes"}
    edit_mode = bool(wants_edit and policy.can_edit(profile["id"]))

    return render(
        request,
        "geoflow_ops/employees/employee_detail.html",
        {
            "profile": profile,
            "create_mode": False,
            "org_units": org_units,
            "departments": departments,
            "managers": managers,
            "employee_roles": employee_roles,
            "edit_mode": edit_mode,
            "can_edit_profile": policy.can_edit(profile["id"]),
            "can_edit_admin_fields": policy.can_edit_admin_fields(profile["id"]),
            "can_assign_roles": policy.can_assign_roles,
            "can_list_employees": policy.can_list,
            "photo_attachment": photo_attachment,
            "photo_url": photo_url,
            "doc_attachments": doc_attachments,
            "education": education,
            "qualifications": qualifications,
            "technical_grades": technical_grades,
            "careers": careers,
            "technical_grade_options": _settings_options(alias, "technical_grade"),
        },
    )


def employees_create(request):
    alias = require_tenant_context(request)
    policy = employee_access_policy(request, alias)
    if not policy.can_create:
        raise PermissionDenied("Permission denied")
    _require_role_code_column(alias)

    if request.method == "POST":
        rejected = _reject_rrn_input(request)
        if rejected:
            return rejected
        email = str(request.POST.get("email") or "").strip().lower()
        name = str(request.POST.get("name") or "").strip()
        if not email or not name:
            return HttpResponseBadRequest("이메일과 이름은 필수입니다.")
        with connections[alias].cursor() as cur:
            cur.execute("SELECT 1 FROM hr.employee_profile WHERE lower(email)=lower(%s) LIMIT 1", [email])
            if cur.fetchone():
                return HttpResponseBadRequest("이미 등록된 이메일입니다.")

        fields = {
            "phone": _optional(request, "phone"),
            "title": _optional(request, "title"),
            "status": _optional(request, "status") or "재직",
            "hire_date": _parse_iso_date(request.POST.get("hire_date")),
            "term_date": _parse_iso_date(request.POST.get("term_date")),
            "org_unit_id": _optional(request, "org_unit_id"),
            "department_id": _optional(request, "department_id"),
            "position_grade": _optional(request, "position_grade"),
            "emp_type": _optional(request, "emp_type"),
            "emp_no": _optional(request, "emp_no"),
            "manager_id": _optional(request, "manager_id"),
            "addr_road": _optional(request, "addr_road"),
            "addr_detail": _optional(request, "addr_detail"),
            "addr_zip": _optional(request, "addr_zip"),
        }
        with transaction.atomic(using=alias):
            with connections[alias].cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO hr.employee_profile
                        (email, name, phone, title, status, hire_date, term_date,
                         org_unit_id, department_id, position_grade, emp_type, emp_no,
                         manager_id, addr_road, addr_detail, addr_zip, created_at, updated_at)
                    VALUES
                        (%s, %s, %s, %s, %s, %s, %s,
                         NULLIF(%s,'')::uuid, NULLIF(%s,'')::uuid, %s, %s, %s,
                         NULLIF(%s,'')::uuid, %s, %s, %s, now(), now())
                    RETURNING id::text
                    """,
                    [
                        email, name, fields["phone"], fields["title"], fields["status"],
                        fields["hire_date"], fields["term_date"], fields["org_unit_id"],
                        fields["department_id"], fields["position_grade"], fields["emp_type"],
                        fields["emp_no"], fields["manager_id"], fields["addr_road"],
                        fields["addr_detail"], fields["addr_zip"],
                    ],
                )
                new_id = cur.fetchone()[0]
        messages.success(request, "직원을 등록했습니다.")
        return redirect("tenant:employees_detail", emp_id=new_id)

    return render(
        request,
        "geoflow_ops/employees/employee_detail.html",
        {
            "profile": _empty_profile(),
            "create_mode": True,
            "edit_mode": True,
            "can_edit_profile": True,
            "can_edit_admin_fields": True,
            "can_assign_roles": policy.can_assign_roles,
            "can_list_employees": True,
            "org_units": _load_org_units(alias),
            "departments": [],
            "managers": _load_managers(alias),
            "employee_roles": [],
            "photo_attachment": None,
            "photo_url": None,
            "doc_attachments": [],
            "education": [],
            "qualifications": [],
            "technical_grades": [],
            "careers": [],
            "technical_grade_options": _settings_options(alias, "technical_grade"),
        },
    )
