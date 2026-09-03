from __future__ import annotations

from datetime import date

from django import template
from django.db import connections

from control.middleware import current_db_alias
from geoflow_ops.models import Attachment
from geoflow_ops.services.tenant_settings import settings_options

register = template.Library()


ROLE_LABELS = {
    "tenant_admin": "테넌트 관리자",
    "tenant_administrator": "테넌트 관리자",
    "tenant_manager": "매니저",
    "manager": "매니저",
    "group_admin": "그룹 관리자",
    "project_admin": "프로젝트 관리자",
    "project_manager": "프로젝트 관리자",
    "projectmanager": "프로젝트 관리자",
    "pm": "프로젝트 관리자",
    "project_coordinator": "프로젝트 코디네이터",
    "project_leader": "프로젝트 코디네이터",
    "projectleader": "프로젝트 코디네이터",
    "leader": "프로젝트 코디네이터",
    "worker": "작업자",
    "project_worker": "작업자",
    "viewer": "조회자",
    "project_viewer": "조회자",
}
ROLE_CLASSES = {
    "tenant_admin": "bg-primary",
    "tenant_administrator": "bg-primary",
    "tenant_manager": "bg-primary",
    "manager": "bg-primary",
    "group_admin": "bg-primary",
    "project_admin": "bg-info text-dark",
    "project_manager": "bg-info text-dark",
    "projectmanager": "bg-info text-dark",
    "pm": "bg-info text-dark",
    "project_coordinator": "bg-warning text-dark",
    "project_leader": "bg-warning text-dark",
    "projectleader": "bg-warning text-dark",
    "leader": "bg-warning text-dark",
    "worker": "bg-success",
    "project_worker": "bg-success",
    "viewer": "bg-secondary",
    "project_viewer": "bg-secondary",
}
STATUS_CLASSES = {
    "재직": "bg-success",
    "휴직": "bg-warning text-dark",
    "퇴사": "bg-secondary",
    "퇴직": "bg-secondary",
}
PREVIEWABLE_MIME_TYPES = {
    "application/pdf",
    "image/jpeg",
    "image/jpg",
    "image/png",
    "image/webp",
    "text/plain",
}
HISTORY_SECTIONS = {"education", "qualification", "technical_grade", "career"}


def _role_value(role, key: str):
    if isinstance(role, dict):
        return role.get(key)
    return getattr(role, key, None)


def _normalize_role(code) -> str:
    return str(code or "").strip().lower().replace("-", "_").replace(" ", "_")


def _tenure_label(hire_date, term_date, status: str) -> str:
    if not hire_date:
        return "-"
    end = term_date if status in {"퇴사", "퇴직"} and term_date else date.today()
    if end < hire_date:
        end = hire_date
    months = (end.year - hire_date.year) * 12 + (end.month - hire_date.month)
    if end.day < hire_date.day:
        months -= 1
    months = max(0, months)
    years, remain = divmod(months, 12)
    if years and remain:
        return f"{years}년 {remain}개월"
    if years:
        return f"{years}년"
    return f"{remain}개월"


def _project_count(alias: str, employee_id) -> int:
    if not employee_id:
        return 0
    with connections[alias].cursor() as cur:
        cur.execute("SELECT to_regclass('prj.project_members') IS NOT NULL")
        row = cur.fetchone()
        if not row or not row[0]:
            return 0
        cur.execute(
            """
            SELECT COUNT(DISTINCT project_id)
              FROM prj.project_members
             WHERE employee_id=%s
               AND membership_status='active'
            """,
            [str(employee_id)],
        )
        count_row = cur.fetchone()
    return int(count_row[0] or 0) if count_row else 0


def _find_name(items, target_id) -> str:
    target = str(target_id or "")
    for item in items or []:
        if str(item.get("id") or "") == target:
            return str(item.get("name") or "")
    return ""


def _settings_label_map(alias: str, field_ref: str) -> dict[str, str]:
    return {
        str(code or "").strip(): str(label or code or "").strip()
        for code, label in settings_options(alias, field_ref, include_inactive=True)
        if str(code or "").strip()
    }


@register.simple_tag(takes_context=True)
def employee_summary(context, profile, employee_roles, org_units, departments, qualifications, technical_grades):
    alias = current_db_alias()
    role_badges = []
    seen = set()
    for role in employee_roles or []:
        code = _normalize_role(_role_value(role, "code") or _role_value(role, "role_code") or role)
        if not code or code in seen:
            continue
        seen.add(code)
        role_badges.append({
            "code": code,
            "label": ROLE_LABELS.get(code, str(_role_value(role, "name") or code)),
            "class": ROLE_CLASSES.get(code, "bg-light text-dark border"),
        })
    fallback_code = _normalize_role((profile or {}).get("role_code"))
    if not role_badges and fallback_code:
        role_badges.append({
            "code": fallback_code,
            "label": ROLE_LABELS.get(fallback_code, fallback_code),
            "class": ROLE_CLASSES.get(fallback_code, "bg-light text-dark border"),
        })

    qualification_names = [
        str(row.get("qualification_name") or "").strip()
        for row in qualifications or []
        if str(row.get("qualification_name") or "").strip()
    ]
    technical_grade_labels = _settings_label_map(alias, "employee.technical_grade")
    technical_labels = []
    for row in technical_grades or []:
        field_name = str(row.get("field_name") or "").strip()
        grade_code = str(row.get("grade_code") or "").strip()
        grade_label = technical_grade_labels.get(grade_code, grade_code)
        label = " · ".join(part for part in (field_name, grade_label) if part)
        if label:
            technical_labels.append(label)

    status_code = str((profile or {}).get("status") or "-")
    status = str((profile or {}).get("status_label") or status_code)
    return {
        "status": status,
        "status_class": STATUS_CLASSES.get(status_code, "bg-light text-dark border"),
        "role_badges": role_badges,
        "tenure": _tenure_label(
            (profile or {}).get("hire_date"),
            (profile or {}).get("term_date"),
            status_code,
        ),
        "project_count": _project_count(alias, (profile or {}).get("id")),
        "org_unit_name": _find_name(org_units, (profile or {}).get("org_unit_id")) or "-",
        "department_name": _find_name(departments, (profile or {}).get("department_id")) or "-",
        "qualification_badges": qualification_names[:3],
        "qualification_extra": max(0, len(qualification_names) - 3),
        "technical_badges": technical_labels[:3],
        "technical_extra": max(0, len(technical_labels) - 3),
    }


def _history_attachment_cache(request, employee_id):
    cache = getattr(request, "_gf_employee_history_attachment_cache", None)
    if cache is None:
        cache = {}
        setattr(request, "_gf_employee_history_attachment_cache", cache)
    key = str(employee_id or "")
    if key in cache:
        return cache[key]

    alias = current_db_alias()
    mapping: dict[tuple[str, str], list[dict]] = {}
    attachments = (
        Attachment.objects.using(alias)
        .filter(
            entity_type="employee",
            entity_id=employee_id,
            purpose="history_doc",
            active=True,
            deleted_at__isnull=True,
        )
        .order_by("ord", "created_at")
    )
    for attachment in attachments:
        parts = str(attachment.kind or "").split(":", 2)
        if len(parts) != 3 or parts[0] != "employee_history" or parts[1] not in HISTORY_SECTIONS:
            continue
        record_id = parts[2]
        item = {
            "id": str(attachment.id),
            "name": attachment.original_name or "파일",
            "mime_type": attachment.mime_type or "",
            "size_bytes": attachment.size_bytes,
            "previewable": (attachment.mime_type or "").lower() in PREVIEWABLE_MIME_TYPES,
        }
        mapping.setdefault((parts[1], record_id), []).append(item)
    cache[key] = mapping
    return mapping


@register.simple_tag(takes_context=True)
def employee_history_documents(context, employee_id, section, record_id):
    request = context.get("request")
    if not request or section not in HISTORY_SECTIONS:
        return []
    mapping = _history_attachment_cache(request, employee_id)
    return mapping.get((section, str(record_id)), [])
