from __future__ import annotations

from datetime import date
import logging

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db import connections, transaction
from django.http import HttpResponseBadRequest, JsonResponse
from django.shortcuts import redirect, render
from control.services_identity import lookup_user_id_from_request
from control.gf_authz.permissions import gf_has_perm

from .models import Attachment
from .services.employee_access import employee_access_policy
from .services.entity_access import require_tenant_context
from .services.s3_service import generate_presigned_get_url
from .services.tenant_settings import settings_options
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


def _employment_status_options(alias: str, current_statuses=()):
    configured = settings_options(alias, "hr.status")
    all_configured = settings_options(alias, "hr.status", include_inactive=True)
    if configured:
        options = [
            {"code": code, "name": label, "ord": index * 10}
            for index, (code, label) in enumerate(configured, start=1)
        ]
    else:
        options = [dict(item) for item in _settings_options(alias, "status")]
    all_labels = {str(code or ""): str(label or code or "") for code, label in all_configured}
    known = {str(item.get("code") or "") for item in options}
    for raw_status in current_statuses:
        status = str(raw_status or "").strip()
        if status and status not in known:
            options.append({"code": status, "name": all_labels.get(status, status), "ord": 9999})
            known.add(status)
    return options


def _retired_status_codes(alias: str) -> list[str]:
    retired_labels = {"퇴사", "퇴직"}
    configured = settings_options(alias, "hr.status", include_inactive=True)
    items = (
        [{"code": code, "name": label} for code, label in configured]
        if configured
        else _settings_options(alias, "status")
    )
    return [
        str(item.get("code") or "").strip()
        for item in items
        if str(item.get("code") or "").strip() in retired_labels
        or str(item.get("name") or "").strip() in retired_labels
    ]


def _audit_actor(request) -> str:
    user_id = lookup_user_id_from_request(request)
    if user_id:
        return str(user_id)
    user = getattr(request, "user", None)
    return str(
        getattr(user, "email", None)
        or getattr(user, "username", None)
        or ""
    ).strip().lower()


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
                   addr_road, addr_detail, addr_zip,
                   is_deleted, deleted_at, deleted_by, delete_reason,
                   restored_at, restored_by
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
        "is_deleted": bool(row[19]), "deleted_at": row[20],
        "deleted_by": row[21] or "", "delete_reason": row[22] or "",
        "restored_at": row[23], "restored_by": row[24] or "",
    }


def _empty_profile():
    return {
        "id": None, "email": "", "name": "", "title": "", "role_code": "",
        "status": "재직", "phone": "", "hire_date": None, "term_date": None,
        "org_unit_id": "", "department_id": "", "position_grade": "", "emp_type": "",
        "emp_no": "", "manager_id": "", "central_user_id": None,
        "addr_road": "", "addr_detail": "", "addr_zip": "",
        "is_deleted": False, "deleted_at": None, "deleted_by": "",
        "delete_reason": "", "restored_at": None, "restored_by": "",
    }


def employees_list(request):
    alias = require_tenant_context(request)
    policy = employee_access_policy(request, alias)
    if not policy.can_list:
        if policy.self_employee_id:
            return redirect("tenant:employees_detail", emp_id=policy.self_employee_id)
        raise PermissionDenied("Employee profile is not linked to this login.")
    include_deleted = bool(
        policy.can_soft_delete
        and gf_has_perm(request, "directory.edit")
        and str(request.GET.get("include_deleted") or "").lower() in {"1", "true", "yes"}
    )
    list_sql = """
            SELECT id::text, email, name, title, role_code, status, phone,
                   position_grade, emp_no, is_deleted, deleted_at
              FROM hr.employee_profile
             WHERE is_deleted = false
             ORDER BY name, email
            """
    if include_deleted:
        list_sql = """
            SELECT id::text, email, name, title, role_code, status, phone,
                   position_grade, emp_no, is_deleted, deleted_at
              FROM hr.employee_profile
             ORDER BY name, email
            """
    with connections[alias].cursor() as cur:
        cur.execute(list_sql)
        rows = cur.fetchall()
    employees = [
        {
            "id": row[0], "email": row[1] or "", "name": row[2] or "",
            "title": row[3] or "", "role_code": row[4] or "", "status": row[5] or "",
            "phone": row[6] or "", "position_grade": row[7] or "", "emp_no": row[8] or "",
            "is_deleted": bool(row[9]), "deleted_at": row[10],
        }
        for row in rows
    ]
    status_options = _employment_status_options(alias, (item["status"] for item in employees))
    status_labels = {item["code"]: item["name"] for item in status_options}
    for employee in employees:
        employee["status_label"] = status_labels.get(employee["status"], employee["status"] or "-")
    return render(
        request,
        "geoflow_ops/employees/employee_list.html",
        {
            "employees": employees,
            "employee_access": policy,
            "employment_statuses": status_options,
            "include_deleted": include_deleted,
            "can_manage_deleted_employees": bool(
                policy.can_soft_delete and gf_has_perm(request, "directory.edit")
            ),
        },
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


def employee_soft_delete(request, emp_id, *, alias: str, policy):
    if (
        not policy.can_soft_delete
        or not policy.can_edit_admin_fields(emp_id)
        or not gf_has_perm(request, "directory.edit")
    ):
        raise PermissionDenied("Permission denied")
    if str(policy.self_employee_id or "") == str(emp_id):
        return HttpResponseBadRequest("현재 로그인한 직원은 삭제 처리할 수 없습니다.")
    reason = str(request.POST.get("delete_reason") or "").strip()
    if not reason:
        return HttpResponseBadRequest("삭제 사유를 입력하세요.")
    if len(reason) > 1000:
        return HttpResponseBadRequest("삭제 사유는 1000자 이내로 입력하세요.")

    retired_codes = _retired_status_codes(alias)
    if not retired_codes:
        return HttpResponseBadRequest("환경설정에서 퇴사 상태를 확인할 수 없습니다.")
    actor = _audit_actor(request)
    if not actor:
        raise PermissionDenied("Authenticated central identity is required")

    with transaction.atomic(using=alias):
        with connections[alias].cursor() as cur:
            cur.execute(
                """
                UPDATE hr.employee_profile
                   SET is_deleted=true,
                       deleted_at=now(),
                       deleted_by=%s,
                       delete_reason=%s,
                       restored_at=NULL,
                       restored_by=NULL,
                       updated_at=now()
                 WHERE id=%s
                   AND is_deleted=false
                   AND status = ANY(%s::text[])
                """,
                [actor, reason, str(emp_id), retired_codes],
            )
            changed = cur.rowcount
    if changed != 1:
        return HttpResponseBadRequest("퇴사 상태의 삭제되지 않은 직원만 삭제 처리할 수 있습니다.")
    messages.success(request, "직원을 삭제 목록으로 이동했습니다. 기존 이력과 연결 정보는 유지됩니다.")
    return redirect("tenant:employees_list")


def employee_restore(request, emp_id, *, alias: str, policy):
    if (
        not policy.can_soft_delete
        or not policy.can_edit_admin_fields(emp_id)
        or not gf_has_perm(request, "directory.edit")
    ):
        raise PermissionDenied("Permission denied")
    actor = _audit_actor(request)
    if not actor:
        raise PermissionDenied("Authenticated central identity is required")
    with transaction.atomic(using=alias):
        with connections[alias].cursor() as cur:
            cur.execute(
                """
                UPDATE hr.employee_profile
                   SET is_deleted=false,
                       restored_at=now(),
                       restored_by=%s,
                       updated_at=now()
                 WHERE id=%s
                   AND is_deleted=true
                """,
                [actor, str(emp_id)],
            )
            changed = cur.rowcount
    if changed != 1:
        return HttpResponseBadRequest("복구할 삭제 직원이 없습니다.")
    messages.success(request, "직원을 복구했습니다. 재직상태는 기존 퇴사 상태로 유지됩니다.")
    return redirect("tenant:employees_detail", emp_id=emp_id)


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
    if profile["is_deleted"] and not policy.can_soft_delete:
        raise PermissionDenied("Permission denied")

    if request.method == "POST":
        if profile["is_deleted"]:
            raise PermissionDenied("Deleted employee profiles must be restored before editing")
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
    edit_mode = bool(wants_edit and policy.can_edit(profile["id"]) and not profile["is_deleted"])
    status_options = _employment_status_options(alias, [profile["status"]])
    status_labels = {item["code"]: item["name"] for item in status_options}
    profile["status_label"] = status_labels.get(profile["status"], profile["status"] or "-")
    retired_codes = set(_retired_status_codes(alias))
    can_soft_delete = bool(
        policy.can_soft_delete
        and gf_has_perm(request, "directory.edit")
        and policy.can_edit_admin_fields(profile["id"])
        and str(policy.self_employee_id or "") != str(profile["id"])
    )

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
            "can_assign_roles": bool(policy.can_assign_roles and not profile["is_deleted"]),
            "can_list_employees": policy.can_list,
            "can_delete_employee": bool(
                can_soft_delete and not profile["is_deleted"] and profile["status"] in retired_codes
            ),
            "can_restore_employee": bool(can_soft_delete and profile["is_deleted"]),
            "photo_attachment": photo_attachment,
            "photo_url": photo_url,
            "doc_attachments": doc_attachments,
            "education": education,
            "qualifications": qualifications,
            "technical_grades": technical_grades,
            "careers": careers,
            "technical_grade_options": _settings_options(alias, "technical_grade"),
            "employment_statuses": status_options,
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
            cur.execute(
                "SELECT is_deleted FROM hr.employee_profile WHERE lower(email)=lower(%s) LIMIT 1",
                [email],
            )
            existing = cur.fetchone()
            if existing:
                message = (
                    "삭제된 직원에 같은 이메일이 있습니다. 삭제된 직원 보기에서 복구한 뒤 수정하세요."
                    if bool(existing[0])
                    else "이미 등록된 이메일입니다."
                )
                return HttpResponseBadRequest(message)

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
            "can_delete_employee": False,
            "can_restore_employee": False,
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
            "employment_statuses": _employment_status_options(alias),
        },
    )
