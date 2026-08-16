from __future__ import annotations

import re
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import connections, transaction
from django.http import HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.dateparse import parse_date
from django.views.decorators.http import require_GET, require_POST

from control.catalog import services_tenant as cat_svc
from control.catalog.models import CategoryFacetOption, CategoryNode, CategoryParent
from control.gf_authz.permissions import gf_has_perm, gf_perm_required

from .models import Project
from .services.entity_access import require_tenant_context

TASK_STATUS_CHOICES = (
    ("pending", "대기"),
    ("active", "진행중"),
    ("done", "완료"),
    ("hold", "보류"),
    ("cancel", "취소"),
)
TASK_STATUSES = {code for code, _label in TASK_STATUS_CHOICES}
TASK_STATUS_LABELS = dict(TASK_STATUS_CHOICES)
MAX_VARIANCE_REASON = 2000
MAX_REMARK = 255


def _parse_uuid(value):
    try:
        return UUID(str(value))
    except (TypeError, ValueError, AttributeError):
        return None


def _parse_decimal(value, *, field: str):
    if value in (None, ""):
        return None, None
    try:
        return Decimal(str(value)), None
    except (InvalidOperation, TypeError, ValueError):
        return None, f"{field} 값이 올바른 숫자가 아닙니다."


def _completion_validation(status: str, design_qty, completed_qty, variance_reason: str):
    if status != "done":
        return None
    if design_qty is not None and completed_qty is not None and design_qty != completed_qty:
        if not variance_reason.strip():
            return "설계 물량과 실적 물량이 다르면 차이 사유를 입력해야 완료할 수 있습니다."
    return None


def _load_task_rows(alias: str, project_id):
    with connections[alias].cursor() as cur:
        cur.execute(
            """
            SELECT id::text, lv2_id::text, lv3_id::text, unit,
                   design_qty, progress_qty, completed_qty, status,
                   completed_at, assignee_employee_id::text,
                   variance_reason, remark
              FROM prj.scope_item
             WHERE project_id = %s
               AND lv3_id IS NOT NULL
               AND lv4_id IS NULL
             ORDER BY created_at, id
            """,
            [str(project_id)],
        )
        raw = cur.fetchall()

    if not raw:
        return []

    lv2_ids = {row[1] for row in raw if row[1]}
    lv3_ids = {row[2] for row in raw if row[2]}
    central = cat_svc.CENTRAL_ALIAS
    l2_nodes = list(CategoryNode.objects.using(central).filter(id__in=lv2_ids))
    l2_map = {str(node.id): node for node in l2_nodes}
    l3_nodes = list(CategoryFacetOption.objects.using(central).filter(id__in=lv3_ids))
    l3_map = {str(node.id): node for node in l3_nodes}

    parents = list(CategoryParent.objects.using(central).filter(child_id__in=lv2_ids))
    child_to_parent = {str(row.child_id): str(row.parent_id) for row in parents}
    l1_ids = {row.parent_id for row in parents}
    l1_nodes = list(CategoryNode.objects.using(central).filter(id__in=l1_ids))
    l1_map = {str(node.id): node for node in l1_nodes}

    assignee_ids = {row[9] for row in raw if row[9]}
    assignee_map = {}
    if assignee_ids:
        with connections[alias].cursor() as cur:
            cur.execute(
                "SELECT id::text, name, title FROM hr.employee_profile WHERE id = ANY(%s::uuid[])",
                [sorted(assignee_ids)],
            )
            assignee_map = {
                row[0]: {"name": row[1] or "", "title": row[2] or ""}
                for row in cur.fetchall()
            }

    rows = []
    for row in raw:
        l2 = l2_map.get(row[1])
        l3 = l3_map.get(row[2])
        l1 = l1_map.get(child_to_parent.get(row[1], ""))
        assignee = assignee_map.get(row[9], {}) if row[9] else {}
        status = row[7] if row[7] in TASK_STATUSES else "pending"
        rows.append(
            {
                "item_id": row[0],
                "l1_name": getattr(l1, "name", "") or "",
                "l1_ord": getattr(l1, "ord", 0) or 0,
                "l2_name": getattr(l2, "name", "") or "",
                "l2_code": getattr(l2, "code", "") or "",
                "l2_ord": getattr(l2, "ord", 0) or 0,
                "l3_name": getattr(l3, "name", "") or "",
                "l3_code": getattr(l3, "code", "") or "",
                "l3_ord": getattr(l3, "ord", 0) or 0,
                "unit": row[3] or "",
                "design_qty": row[4],
                "progress_qty": row[5],
                "completed_qty": row[6],
                "status": status,
                "status_label": TASK_STATUS_LABELS[status],
                "completed_at": row[8],
                "assignee_employee_id": row[9] or "",
                "assignee_name": assignee.get("name", ""),
                "assignee_title": assignee.get("title", ""),
                "variance_reason": row[10] or "",
                "remark": row[11] or "",
            }
        )

    return sorted(
        rows,
        key=lambda item: (
            item["l1_ord"], item["l1_name"], item["l2_ord"], item["l2_name"],
            item["l3_ord"], item["l3_name"], item["item_id"],
        ),
    )


def _employee_options(alias: str):
    with connections[alias].cursor() as cur:
        cur.execute(
            """
            SELECT id::text, name, title, department_id::text
              FROM hr.employee_profile
             WHERE status IS NULL OR status <> '퇴사'
             ORDER BY name, title
            """
        )
        return [
            {
                "id": row[0],
                "name": row[1] or "",
                "title": row[2] or "",
                "department_id": row[3] or "",
            }
            for row in cur.fetchall()
        ]


@login_required
@gf_perm_required("projects.edit")
@require_GET
def project_task_modal(request, pk):
    alias = require_tenant_context(request)
    project = get_object_or_404(Project.objects.using(alias).select_related("contract"), pk=pk)
    task_rows = _load_task_rows(alias, project.pk)
    can_assign = gf_has_perm(request, "directory.view")
    employees = _employee_options(alias) if can_assign else []
    counts = {code: 0 for code in TASK_STATUSES}
    for row in task_rows:
        counts[row["status"]] += 1

    return render(
        request,
        "geoflow_ops/projects/project_summary.html",
        {
            "project": project,
            "task_rows": task_rows,
            "task_status_choices": TASK_STATUS_CHOICES,
            "task_status_counts": counts,
            "employee_options": employees,
            "can_assign": can_assign,
            "execution_mode": True,
        },
    )


@login_required
@gf_perm_required("projects.edit")
@require_POST
def project_task_save(request, pk):
    alias = require_tenant_context(request)
    project = get_object_or_404(Project.objects.using(alias), pk=pk)
    can_assign = gf_has_perm(request, "directory.view")

    row_re = re.compile(r"^rows\[([0-9a-fA-F-]{36})\]\[(\w+)\]$")
    submitted: dict[str, dict[str, str]] = {}
    for key, value in request.POST.items():
        match = row_re.match(key)
        if not match:
            continue
        submitted.setdefault(match.group(1), {})[match.group(2)] = value

    if not submitted:
        return HttpResponseBadRequest("저장할 업무가 없습니다.")

    item_ids = []
    for item_id in submitted:
        parsed = _parse_uuid(item_id)
        if not parsed:
            return HttpResponseBadRequest("잘못된 업무 ID입니다.")
        item_ids.append(str(parsed))

    with connections[alias].cursor() as cur:
        cur.execute(
            """
            SELECT id::text, design_qty, assignee_employee_id::text
              FROM prj.scope_item
             WHERE project_id=%s AND id = ANY(%s::uuid[])
            """,
            [str(project.pk), item_ids],
        )
        existing = {
            row[0]: {"design_qty": row[1], "assignee_employee_id": row[2] or ""}
            for row in cur.fetchall()
        }
    if set(existing) != set(item_ids):
        return HttpResponseBadRequest("프로젝트에 속하지 않은 업무가 포함되어 있습니다.")

    prepared: list[dict[str, Any]] = []
    assignee_ids = set()
    for item_id, data in submitted.items():
        status = (data.get("status") or "pending").strip().lower()
        if status not in TASK_STATUSES:
            return HttpResponseBadRequest("잘못된 업무 상태입니다.")

        progress_qty, error = _parse_decimal(data.get("progress_qty"), field="진행 물량")
        if error:
            return HttpResponseBadRequest(error)
        completed_qty, error = _parse_decimal(data.get("completed_qty"), field="실적 물량")
        if error:
            return HttpResponseBadRequest(error)

        variance_reason = (data.get("variance_reason") or "").strip()
        if len(variance_reason) > MAX_VARIANCE_REASON:
            return HttpResponseBadRequest("차이 사유가 너무 깁니다.")
        remark = (data.get("remark") or "").strip()
        if len(remark) > MAX_REMARK:
            return HttpResponseBadRequest("비고가 너무 깁니다.")

        completed_at_raw = (data.get("completed_at") or "").strip()
        completed_at = parse_date(completed_at_raw) if completed_at_raw else None
        if completed_at_raw and completed_at is None:
            return HttpResponseBadRequest("완료일은 YYYY-MM-DD 형식이어야 합니다.")
        if status == "done" and completed_at is None:
            completed_at = date.today()
        if status != "done":
            completed_at = None

        validation_error = _completion_validation(
            status,
            existing[item_id]["design_qty"],
            completed_qty,
            variance_reason,
        )
        if validation_error:
            return HttpResponseBadRequest(validation_error)

        assignee = existing[item_id]["assignee_employee_id"]
        if can_assign and "assignee_employee_id" in data:
            raw_assignee = (data.get("assignee_employee_id") or "").strip()
            if raw_assignee:
                parsed_assignee = _parse_uuid(raw_assignee)
                if not parsed_assignee:
                    return HttpResponseBadRequest("잘못된 담당자입니다.")
                assignee = str(parsed_assignee)
                assignee_ids.add(assignee)
            else:
                assignee = ""

        prepared.append(
            {
                "id": item_id,
                "status": status,
                "progress_qty": progress_qty,
                "completed_qty": completed_qty,
                "completed_at": completed_at,
                "assignee_employee_id": assignee or None,
                "variance_reason": variance_reason or None,
                "remark": remark or None,
            }
        )

    if assignee_ids:
        with connections[alias].cursor() as cur:
            cur.execute(
                """
                SELECT id::text
                  FROM hr.employee_profile
                 WHERE id = ANY(%s::uuid[])
                   AND (status IS NULL OR status <> '퇴사')
                """,
                [sorted(assignee_ids)],
            )
            valid_assignees = {row[0] for row in cur.fetchall()}
        if valid_assignees != assignee_ids:
            return HttpResponseBadRequest("현재 배정할 수 없는 담당자가 포함되어 있습니다.")

    with transaction.atomic(using=alias):
        with connections[alias].cursor() as cur:
            for row in prepared:
                cur.execute(
                    """
                    UPDATE prj.scope_item
                       SET status=%s,
                           progress_qty=%s,
                           completed_qty=%s,
                           completed_at=%s,
                           assignee_employee_id=%s,
                           variance_reason=%s,
                           remark=%s,
                           updated_at=now()
                     WHERE id=%s AND project_id=%s
                    """,
                    [
                        row["status"], row["progress_qty"], row["completed_qty"],
                        row["completed_at"], row["assignee_employee_id"],
                        row["variance_reason"], row["remark"], row["id"], str(project.pk),
                    ],
                )
                if cur.rowcount != 1:
                    raise RuntimeError("project task update lost scope")

    messages.success(request, "프로젝트 업무 실행현황을 저장했습니다.")
    return redirect("tenant:project_summary", pk=project.pk)
