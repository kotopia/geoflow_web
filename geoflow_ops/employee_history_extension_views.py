from __future__ import annotations

from django.db import connections
from django.http import JsonResponse

from . import views_employee_history
from . import views_employee_profile
from .services.entity_access import require_tenant_context


# Keep the shared history configuration as the single save contract while adding
# the new employee-history fields introduced after the original foundation.
views_employee_profile.OPTION_SYSTEM_KEYS.setdefault(
    "education_degree", "employee.education_degree"
)
views_employee_profile.OPTION_SYSTEM_KEYS.setdefault(
    "education_status", "employee.education_status"
)

_career = views_employee_profile.HISTORY_SECTIONS.get("career")
if _career:
    fields = list(_career.get("fields") or ())
    if not any(name == "certificate_no" for name, _ in fields):
        insert_at = next(
            (idx for idx, (name, _) in enumerate(fields) if name == "duties"),
            len(fields),
        )
        fields.insert(insert_at, ("certificate_no", "text"))
        _career["fields"] = tuple(fields)


def history_save(request, emp_id):
    return views_employee_history.history_save(request, emp_id)


def history_detail(request, emp_id):
    alias = require_tenant_context(request)
    section = str(request.GET.get("section") or "").strip().lower()
    record_id = str(request.GET.get("record_id") or "").strip()
    if section != "career" or not record_id:
        return JsonResponse({"error": "경력 이력 ID를 확인하세요."}, status=400)

    with connections[alias].cursor() as cur:
        cur.execute(
            """
            SELECT certificate_no
              FROM hr.employee_career
             WHERE id=%s AND employee_id=%s AND active=true
             LIMIT 1
            """,
            [record_id, str(emp_id)],
        )
        row = cur.fetchone()
    if not row:
        return JsonResponse({"error": "경력 이력을 찾을 수 없습니다."}, status=404)
    return JsonResponse({"certificate_no": row[0] or ""})
