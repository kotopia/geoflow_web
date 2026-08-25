from __future__ import annotations

from collections import defaultdict
from uuid import UUID, uuid4

from django.contrib import messages
from django.db import connections, transaction
from django.http import HttpResponseBadRequest
from django.shortcuts import redirect, render

from .process_workflow import STAGE_CHOICES
from .services.entity_access import require_tenant_context


NODE_TYPES = {"group", "category", "value"}
# These rows remain in the database for compatibility/history but are no longer
# user-facing settings. Contract lifecycle is now derived from event workflow.
HIDDEN_SETTINGS_SYSTEM_KEYS = {
    "contract.status",
    "hr.position_grade",
    "hr.position_title",
}

_CANONICAL_EVENT_STAGE_NAMES = {
    f"event.stage.{choice.code}": choice.label for choice in STAGE_CHOICES
}


def _is_immutable_event_stage(system_key: object) -> bool:
    key = str(system_key or "").strip()
    return key == "event.stage" or key.startswith("event.stage.")


def _uuid_or_none(value):
    if value in (None, ""):
        return None
    try:
        return UUID(str(value))
    except (TypeError, ValueError, AttributeError):
        return None


def _load_nodes(alias: str):
    with connections[alias].cursor() as cur:
        cur.execute(
            """
            SELECT id::text, parent_id::text, code, name, node_type, value,
                   description, ord, active, system_key, locked
              FROM ops.settings_nodes
             ORDER BY COALESCE(parent_id::text, ''), ord, name, code
            """
        )
        rows = cur.fetchall()
    return [
        {
            "id": row[0],
            "parent_id": row[1] or "",
            "code": row[2] or "",
            # Required stages are immutable system vocabulary. Display the
            # current canonical label without rewriting tenant history rows.
            "name": _CANONICAL_EVENT_STAGE_NAMES.get(row[9] or "", row[3] or ""),
            "node_type": row[4] or "value",
            "value": row[5] or "",
            "description": row[6] or "",
            "ord": row[7] or 0,
            "active": bool(row[8]),
            "system_key": row[9] or "",
            "locked": bool(row[10]),
            "immutable": _is_immutable_event_stage(row[9]),
        }
        for row in rows
    ]


def _visible_nodes(nodes):
    """Hide deprecated setting roots and all descendants without deleting data."""
    hidden_ids = {
        node["id"]
        for node in nodes
        if node.get("system_key") in HIDDEN_SETTINGS_SYSTEM_KEYS
    }
    changed = True
    while changed:
        changed = False
        for node in nodes:
            if node["id"] not in hidden_ids and node.get("parent_id") in hidden_ids:
                hidden_ids.add(node["id"])
                changed = True
    return [node for node in nodes if node["id"] not in hidden_ids]


def _load_org_units(alias: str):
    with connections[alias].cursor() as cur:
        cur.execute("SELECT id::text, name FROM ops.my_org_units ORDER BY name")
        return [{"id": row[0], "name": row[1] or "-"} for row in cur.fetchall()]


def _load_departments(alias: str):
    with connections[alias].cursor() as cur:
        cur.execute(
            """
            SELECT d.id::text, d.org_unit_id::text, COALESCE(o.name, ''), d.name, d.active
              FROM hr.departments d
              LEFT JOIN ops.my_org_units o ON o.id=d.org_unit_id
             ORDER BY COALESCE(o.name, ''), d.name
            """
        )
        return [
            {
                "id": row[0],
                "org_unit_id": row[1] or "",
                "org_unit_name": row[2] or "-",
                "name": row[3] or "",
                "active": bool(row[4]),
            }
            for row in cur.fetchall()
        ]


def _build_tree(nodes):
    by_parent = defaultdict(list)
    for node in nodes:
        by_parent[node["parent_id"]].append(node)

    def attach(parent_id: str, depth: int):
        result = []
        for node in sorted(by_parent.get(parent_id, []), key=lambda x: (x["ord"], x["name"], x["code"])):
            item = dict(node)
            item["depth"] = depth
            item["children"] = attach(node["id"], depth + 1)
            result.append(item)
        return result

    return attach("", 0)


def settings_page(request):
    alias = require_tenant_context(request)
    nodes = _visible_nodes(_load_nodes(alias))
    return render(
        request,
        "geoflow_ops/settings/settings_page.html",
        {
            "settings_tree": _build_tree(nodes),
            "settings_nodes": nodes,
            "org_units": _load_org_units(alias),
            "departments": _load_departments(alias),
        },
    )


def settings_node_save(request):
    alias = require_tenant_context(request)
    node_id = _uuid_or_none(request.POST.get("node_id"))
    parent_id = _uuid_or_none(request.POST.get("parent_id"))
    code = str(request.POST.get("code") or "").strip()
    name = str(request.POST.get("name") or "").strip()
    node_type = str(request.POST.get("node_type") or "value").strip().lower()
    value = str(request.POST.get("value") or "").strip() or None
    description = str(request.POST.get("description") or "").strip() or None
    active = str(request.POST.get("active") or "").lower() in {"1", "true", "yes", "on"}
    try:
        ord_value = int(request.POST.get("ord") or 0)
    except (TypeError, ValueError):
        ord_value = 0

    if not code or not name or node_type not in NODE_TYPES:
        return HttpResponseBadRequest("환경설정 코드, 이름, 유형을 확인하세요.")

    with transaction.atomic(using=alias):
        with connections[alias].cursor() as cur:
            if parent_id:
                cur.execute("SELECT id FROM ops.settings_nodes WHERE id=%s", [str(parent_id)])
                if not cur.fetchone():
                    return HttpResponseBadRequest("상위 환경설정 항목을 찾을 수 없습니다.")

            if node_id:
                cur.execute(
                    "SELECT locked, code, parent_id::text, node_type, system_key FROM ops.settings_nodes WHERE id=%s FOR UPDATE",
                    [str(node_id)],
                )
                existing = cur.fetchone()
                if not existing:
                    return HttpResponseBadRequest("환경설정 항목을 찾을 수 없습니다.")
                locked = bool(existing[0])
                system_key = existing[4] or ""
                if _is_immutable_event_stage(system_key):
                    return HttpResponseBadRequest("필수 업무단계는 시스템 기준값으로 수정할 수 없습니다.")
                if locked:
                    code = existing[1]
                    parent_id = _uuid_or_none(existing[2])
                    node_type = existing[3]
                    if node_type != "value":
                        active = True
                cur.execute(
                    """
                    UPDATE ops.settings_nodes
                       SET parent_id=%s, code=%s, name=%s, node_type=%s,
                           value=%s, description=%s, ord=%s, active=%s,
                           updated_at=now()
                     WHERE id=%s
                    """,
                    [str(parent_id) if parent_id else None, code, name, node_type,
                     value, description, ord_value, active, str(node_id)],
                )
                messages.success(request, "환경설정 항목을 수정했습니다.")
            else:
                cur.execute(
                    """
                    INSERT INTO ops.settings_nodes
                        (parent_id, code, name, node_type, value, description, ord, active)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    [str(parent_id) if parent_id else None, code, name, node_type,
                     value, description, ord_value, active],
                )
                messages.success(request, "환경설정 항목을 추가했습니다.")

    return redirect("tenant:settings_page")


def department_save(request):
    """Manage the real HR department master from the Environment Settings page."""
    alias = require_tenant_context(request)
    department_id = _uuid_or_none(request.POST.get("department_id"))
    org_unit_id = _uuid_or_none(request.POST.get("org_unit_id"))
    name = str(request.POST.get("name") or "").strip()
    active = str(request.POST.get("active") or "").lower() in {"1", "true", "yes", "on"}
    if not org_unit_id or not name:
        return HttpResponseBadRequest("회사와 담당부서 이름을 확인하세요.")

    with transaction.atomic(using=alias):
        with connections[alias].cursor() as cur:
            cur.execute("SELECT 1 FROM ops.my_org_units WHERE id=%s", [str(org_unit_id)])
            if not cur.fetchone():
                return HttpResponseBadRequest("회사를 찾을 수 없습니다.")
            cur.execute(
                """
                SELECT id::text
                  FROM hr.departments
                 WHERE org_unit_id=%s AND lower(name)=lower(%s)
                   AND (%s::uuid IS NULL OR id<>%s::uuid)
                 LIMIT 1
                """,
                [str(org_unit_id), name, str(department_id) if department_id else None,
                 str(department_id) if department_id else None],
            )
            if cur.fetchone():
                return HttpResponseBadRequest("같은 회사에 동일한 담당부서가 이미 있습니다.")

            if department_id:
                cur.execute(
                    """
                    UPDATE hr.departments
                       SET org_unit_id=%s, name=%s, active=%s, updated_at=now()
                     WHERE id=%s
                    """,
                    [str(org_unit_id), name, active, str(department_id)],
                )
                if cur.rowcount != 1:
                    return HttpResponseBadRequest("담당부서를 찾을 수 없습니다.")
                messages.success(request, "담당부서를 수정했습니다.")
            else:
                cur.execute(
                    """
                    SELECT EXISTS (
                        SELECT 1
                          FROM information_schema.columns
                         WHERE table_schema='hr'
                           AND table_name='departments'
                           AND column_name='code'
                    )
                    """
                )
                legacy_code_column = bool(cur.fetchone()[0])
                if legacy_code_column:
                    department_code = f"dept-{uuid4().hex}"
                    cur.execute(
                        "INSERT INTO hr.departments (org_unit_id, code, name, active) VALUES (%s, %s, %s, %s)",
                        [str(org_unit_id), department_code, name, active],
                    )
                else:
                    cur.execute(
                        "INSERT INTO hr.departments (org_unit_id, name, active) VALUES (%s, %s, %s)",
                        [str(org_unit_id), name, active],
                    )
                messages.success(request, "담당부서를 추가했습니다.")
    return redirect("tenant:settings_page")
