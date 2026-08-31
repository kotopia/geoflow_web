from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date

from django.db import connections
from django.db.models import Q
from django.shortcuts import render
from django.utils.dateparse import parse_date

from control.catalog import services_tenant as cat_svc
from control.catalog.models import CategoryFacetOption, CategoryNode
from control.gf_authz.permissions import gf_has_perm

from .models import Contract, Project
from .services.entity_access import require_tenant_context

PROJECT_STATUS_GROUPS = {
    "planned": {"planned", "대기", "계약전"},
    "active": {"active", "진행", "진행중"},
    "pause": {"pause", "paused", "중지", "보류"},
    "complete": {"complete", "completed", "완료"},
    "cancel": {"cancel", "canceled", "cancelled", "취소"},
}
TASK_STATUS_LABELS = {
    "pending": "대기",
    "active": "진행중",
    "done": "완료",
    "hold": "보류",
    "cancel": "취소",
}


def _status_group(value):
    text = str(value or "").strip().lower()
    for group, values in PROJECT_STATUS_GROUPS.items():
        if text in {str(item).lower() for item in values}:
            return group
    return "other"


def _parse_bool(value):
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _parse_year(value):
    try:
        year = int(str(value or "").strip())
    except (TypeError, ValueError):
        return None
    return year if 2000 <= year <= 2100 else None


def _terminal_contract_ids(alias: str) -> list[str]:
    """Return terminal contracts from the event ledger only.

    Migration 0026 converted historic completed Contract.status rows into
    closeout_complete events. New workflow completion is closeout_approved;
    both are terminal history, as is an explicit contract cancellation.
    """
    with connections[alias].cursor() as cur:
        cur.execute(
            """
            SELECT DISTINCT contract_id::text
              FROM ops.process_events
             WHERE contract_id IS NOT NULL
               AND COALESCE(status, '') <> 'void'
               AND event_type IN ('closeout_approved', 'closeout_complete', 'contract_cancel')
            """
        )
        return [row[0] for row in cur.fetchall() if row and row[0]]


def _task_rows(alias: str, project_ids):
    if not project_ids:
        return []
    with connections[alias].cursor() as cur:
        cur.execute(
            """
            SELECT s.id::text, s.project_id::text, s.lv2_id::text, s.lv3_id::text,
                   s.unit, s.design_qty, s.progress_qty, s.completed_qty, s.status,
                   s.completed_at, s.assignee_employee_id::text, s.variance_reason,
                   s.remark
              FROM prj.scope_item s
             WHERE s.project_id = ANY(%s::uuid[])
               AND s.lv3_id IS NOT NULL
               AND s.lv4_id IS NULL
             ORDER BY s.updated_at DESC, s.id
            """,
            [sorted(str(value) for value in project_ids)],
        )
        rows = cur.fetchall()
    return [
        {
            "id": row[0], "project_id": row[1], "lv2_id": row[2], "lv3_id": row[3],
            "unit": row[4] or "", "design_qty": row[5], "progress_qty": row[6],
            "completed_qty": row[7], "status": row[8] or "pending",
            "completed_at": row[9], "assignee_employee_id": row[10] or "",
            "variance_reason": row[11] or "", "remark": row[12] or "",
        }
        for row in rows
    ]


def _catalog_maps(tasks):
    lv2_ids = {row["lv2_id"] for row in tasks if row["lv2_id"]}
    lv3_ids = {row["lv3_id"] for row in tasks if row["lv3_id"]}
    central = cat_svc.CENTRAL_ALIAS
    l2 = {
        str(item.id): item.name or ""
        for item in CategoryNode.objects.using(central).filter(id__in=lv2_ids)
    }
    l3 = {
        str(item.id): item.name or ""
        for item in CategoryFacetOption.objects.using(central).filter(id__in=lv3_ids)
    }
    return l2, l3


def _employee_map(alias: str, ids):
    ids = sorted({value for value in ids if value})
    if not ids:
        return {}
    with connections[alias].cursor() as cur:
        cur.execute(
            "SELECT id::text, name, title FROM hr.employee_profile WHERE id = ANY(%s::uuid[])",
            [ids],
        )
        return {
            row[0]: {"name": row[1] or "", "title": row[2] or ""}
            for row in cur.fetchall()
        }


def _employee_options(alias: str):
    with connections[alias].cursor() as cur:
        cur.execute(
            """
            SELECT id::text, name, title
              FROM hr.employee_profile
             WHERE (status IS NULL OR status <> '퇴사')
               AND is_deleted = false
             ORDER BY name, title
            """
        )
        return [
            {"id": row[0], "name": row[1] or "", "title": row[2] or ""}
            for row in cur.fetchall()
        ]


def tenant_dashboard(request):
    alias = require_tenant_context(request)
    can_view_projects = gf_has_perm(request, "projects.view")
    can_view_contracts = gf_has_perm(request, "contracts.view")
    can_view_directory = gf_has_perm(request, "directory.view")

    year = _parse_year(request.GET.get("year"))
    date_from = parse_date(request.GET.get("from") or "")
    date_to = parse_date(request.GET.get("to") or "")
    project_status = str(request.GET.get("status") or "").strip().lower()
    assignee = str(request.GET.get("assignee") or "").strip()
    include_completed = _parse_bool(request.GET.get("include_completed"))

    today = date.today()
    if year and not date_from and not date_to:
        date_from = date(year, 1, 1)
        date_to = date(year, 12, 31)

    terminal_contract_ids = []
    if not include_completed and (can_view_projects or can_view_contracts):
        terminal_contract_ids = _terminal_contract_ids(alias)

    projects = []
    if can_view_projects:
        qs = Project.objects.using(alias).select_related(
            "contract", "contract__client", "contract__sub_client", "contract__org_unit"
        )
        if date_from:
            qs = qs.filter(Q(end_date__gte=date_from) | Q(end_date__isnull=True))
        if date_to:
            qs = qs.filter(Q(start_date__lte=date_to) | Q(start_date__isnull=True))
        if project_status in PROJECT_STATUS_GROUPS:
            qs = qs.filter(status__in=PROJECT_STATUS_GROUPS[project_status])
        if not include_completed and not project_status:
            terminal = PROJECT_STATUS_GROUPS["complete"] | PROJECT_STATUS_GROUPS["cancel"]
            qs = qs.exclude(status__in=terminal)
            if terminal_contract_ids:
                qs = qs.exclude(contract_id__in=terminal_contract_ids)

        if assignee and can_view_directory:
            with connections[alias].cursor() as cur:
                cur.execute(
                    "SELECT DISTINCT project_id::text FROM prj.scope_item WHERE assignee_employee_id=%s",
                    [assignee],
                )
                assigned_project_ids = [row[0] for row in cur.fetchall()]
            qs = qs.filter(id__in=assigned_project_ids)

        projects = list(qs.order_by("end_date", "start_date", "name")[:500])

    project_ids = [project.id for project in projects]
    tasks = _task_rows(alias, project_ids) if can_view_projects else []
    l2_map, l3_map = _catalog_maps(tasks) if tasks else ({}, {})
    employees = _employee_map(alias, [row["assignee_employee_id"] for row in tasks]) if can_view_directory else {}

    project_map = {str(project.id): project for project in projects}
    task_counts_by_project = defaultdict(Counter)
    task_total_by_project = Counter()
    task_variance_by_project = Counter()
    status_counts = Counter()
    unassigned_open = 0
    variance_count = 0

    for task in tasks:
        status = task["status"] if task["status"] in TASK_STATUS_LABELS else "pending"
        task["status"] = status
        task["status_label"] = TASK_STATUS_LABELS[status]
        status_counts[status] += 1
        task_counts_by_project[task["project_id"]][status] += 1
        task_total_by_project[task["project_id"]] += 1
        project = project_map.get(task["project_id"])
        task["project"] = project
        task["l2_name"] = l2_map.get(task["lv2_id"], "")
        task["l3_name"] = l3_map.get(task["lv3_id"], "")
        employee = employees.get(task["assignee_employee_id"], {}) if can_view_directory else {}
        task["assignee_name"] = employee.get("name", "")
        task["assignee_title"] = employee.get("title", "")
        has_variance = (
            task["design_qty"] is not None
            and task["completed_qty"] is not None
            and task["design_qty"] != task["completed_qty"]
        )
        task["has_variance"] = has_variance
        if has_variance:
            variance_count += 1
            task_variance_by_project[task["project_id"]] += 1
        if status in {"pending", "active", "hold"} and not task["assignee_employee_id"]:
            unassigned_open += 1

    project_rows = []
    for project in projects:
        pid = str(project.id)
        total = task_total_by_project[pid]
        counts = task_counts_by_project[pid]
        done = counts["done"]
        project_rows.append(
            {
                "project": project,
                "status_group": _status_group(project.status),
                "task_total": total,
                "task_done": done,
                "task_open": counts["pending"] + counts["active"] + counts["hold"],
                "task_hold": counts["hold"],
                "variance_count": task_variance_by_project[pid],
                "progress_pct": int((done * 100) / total) if total else 0,
            }
        )

    task_queue = [
        task for task in tasks
        if include_completed or task["status"] not in {"done", "cancel"}
    ]
    task_order = {"active": 0, "hold": 1, "pending": 2, "done": 3, "cancel": 4}
    task_queue.sort(
        key=lambda task: (
            task_order.get(task["status"], 9),
            getattr(task.get("project"), "end_date", None) or date.max,
            task["l2_name"], task["l3_name"],
        )
    )
    task_queue = task_queue[:40]

    contracts_count = 0
    if can_view_contracts:
        contract_qs = Contract.objects.using(alias).all()
        if date_from:
            contract_qs = contract_qs.filter(Q(end_date__gte=date_from) | Q(end_date__isnull=True))
        if date_to:
            contract_qs = contract_qs.filter(Q(start_date__lte=date_to) | Q(start_date__isnull=True))
        if not include_completed and terminal_contract_ids:
            contract_qs = contract_qs.exclude(id__in=terminal_contract_ids)
        contracts_count = contract_qs.count()

    available_years = []
    if can_view_projects:
        year_values = set()
        for value in Project.objects.using(alias).values_list("start_date", "end_date"):
            for item in value:
                if item:
                    year_values.add(item.year)
        available_years = sorted(year_values, reverse=True)[:10]

    return render(
        request,
        "geoflow_ops/home.html",
        {
            "can_view_projects": can_view_projects,
            "can_view_contracts": can_view_contracts,
            "can_view_directory": can_view_directory,
            "filters": {
                "year": year or "",
                "from": date_from.isoformat() if date_from else "",
                "to": date_to.isoformat() if date_to else "",
                "status": project_status,
                "assignee": assignee if can_view_directory else "",
                "include_completed": include_completed,
            },
            "available_years": available_years,
            "employee_options": _employee_options(alias) if can_view_directory else [],
            "contracts_count": contracts_count,
            "projects_count": len(projects),
            "task_open_count": status_counts["pending"] + status_counts["active"] + status_counts["hold"],
            "task_done_count": status_counts["done"],
            "task_variance_count": variance_count,
            "task_unassigned_count": unassigned_open,
            "project_rows": project_rows[:100],
            "task_queue": task_queue,
            "today": today,
        },
    )
