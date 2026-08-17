from __future__ import annotations

from collections import defaultdict
from uuid import UUID

from django.contrib import messages
from django.db import connections, transaction
from django.http import HttpResponseBadRequest
from django.shortcuts import redirect, render

from .services.entity_access import require_tenant_context


NODE_TYPES = {"group", "category", "value"}


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
            "name": row[3] or "",
            "node_type": row[4] or "value",
            "value": row[5] or "",
            "description": row[6] or "",
            "ord": row[7] or 0,
            "active": bool(row[8]),
            "system_key": row[9] or "",
            "locked": bool(row[10]),
        }
        for row in rows
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
    nodes = _load_nodes(alias)
    return render(
        request,
        "geoflow_ops/settings/settings_page.html",
        {"settings_tree": _build_tree(nodes), "settings_nodes": nodes},
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
                    "SELECT locked, code, parent_id::text, node_type FROM ops.settings_nodes WHERE id=%s FOR UPDATE",
                    [str(node_id)],
                )
                existing = cur.fetchone()
                if not existing:
                    return HttpResponseBadRequest("환경설정 항목을 찾을 수 없습니다.")
                locked = bool(existing[0])
                if locked:
                    # Stable system categories keep their machine identity and hierarchy.
                    code = existing[1]
                    parent_id = _uuid_or_none(existing[2])
                    node_type = existing[3]
                    active = True
                cur.execute(
                    """
                    UPDATE ops.settings_nodes
                       SET parent_id=%s,
                           code=%s,
                           name=%s,
                           node_type=%s,
                           value=%s,
                           description=%s,
                           ord=%s,
                           active=%s,
                           updated_at=now()
                     WHERE id=%s
                    """,
                    [
                        str(parent_id) if parent_id else None,
                        code,
                        name,
                        node_type,
                        value,
                        description,
                        ord_value,
                        active,
                        str(node_id),
                    ],
                )
                messages.success(request, "환경설정 항목을 수정했습니다.")
            else:
                cur.execute(
                    """
                    INSERT INTO ops.settings_nodes
                        (parent_id, code, name, node_type, value, description, ord, active)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    [
                        str(parent_id) if parent_id else None,
                        code,
                        name,
                        node_type,
                        value,
                        description,
                        ord_value,
                        active,
                    ],
                )
                messages.success(request, "환경설정 항목을 추가했습니다.")

    return redirect("tenant:settings_page")
