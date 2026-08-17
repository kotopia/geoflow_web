from __future__ import annotations

from uuid import UUID

from django.core.exceptions import PermissionDenied
from django.db import connections, transaction
from django.http import HttpResponseBadRequest, JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_GET, require_POST

from .models import Project
from .services.entity_access import require_tenant_context
from .services.project_access import project_access_policy


MEMBER_ROLE_LABELS = {
    "project_manager": "Project Manager",
    "project_leader": "Project Leader",
    "worker": "Worker",
    "viewer": "Viewer",
}


def _uuid(value):
    try:
        return UUID(str(value))
    except (TypeError, ValueError, AttributeError):
        return None


def _table_exists(alias: str, relation: str) -> bool:
    with connections[alias].cursor() as cur:
        cur.execute("SELECT to_regclass(%s) IS NOT NULL", [relation])
        row = cur.fetchone()
    return bool(row and row[0])


def project_member_rows(alias: str, project_id) -> list[dict]:
    if not _table_exists(alias, "prj.project_members"):
        return []
    with connections[alias].cursor() as cur:
        cur.execute(
            """
            SELECT m.id::text,
                   m.employee_id::text,
                   COALESCE(e.name, m.invite_name, ''),
                   COALESCE(e.email, m.invite_email, ''),
                   m.member_role,
                   m.membership_status,
                   m.is_external,
                   COALESCE(e.position_grade, ''),
                   COALESCE(e.title, ''),
                   COALESCE(e.emp_type, '')
              FROM prj.project_members m
              LEFT JOIN hr.employee_profile e ON e.id=m.employee_id
             WHERE m.project_id=%s
               AND m.membership_status <> 'revoked'
             ORDER BY CASE m.member_role
                        WHEN 'project_manager' THEN 1
                        WHEN 'project_leader' THEN 2
                        WHEN 'worker' THEN 3
                        ELSE 4
                      END,
                      COALESCE(e.name, m.invite_name, e.email, m.invite_email, '')
            """,
            [str(project_id)],
        )
        rows = cur.fetchall()
    return [
        {
            "id": row[0],
            "employee_id": row[1] or "",
            "name": row[2] or "",
            "email": row[3] or "",
            "member_role": row[4],
            "member_role_label": MEMBER_ROLE_LABELS.get(row[4], row[4]),
            "membership_status": row[5],
            "is_external": bool(row[6]),
            "position_grade": row[7] or "",
            "title": row[8] or "",
            "emp_type": row[9] or "",
            "legacy_invite": not bool(row[1]),
        }
        for row in rows
    ]


def project_member_options(alias: str, project_id) -> list[dict]:
    if not _table_exists(alias, "hr.employee_profile") or not _table_exists(alias, "prj.project_members"):
        return []
    with connections[alias].cursor() as cur:
        cur.execute(
            """
            SELECT e.id::text, e.name, e.email, e.position_grade, e.title, e.emp_type
              FROM hr.employee_profile e
             WHERE COALESCE(e.status, '재직') <> '퇴사'
               AND NOT EXISTS (
                    SELECT 1
                      FROM prj.project_members m
                     WHERE m.project_id=%s
                       AND m.employee_id=e.id
                       AND m.membership_status <> 'revoked'
               )
             ORDER BY e.name, e.email
            """,
            [str(project_id)],
        )
        rows = cur.fetchall()
    return [
        {
            "id": row[0],
            "name": row[1] or "",
            "email": row[2] or "",
            "position_grade": row[3] or "",
            "title": row[4] or "",
            "emp_type": row[5] or "",
        }
        for row in rows
    ]


def project_member_context(request, alias: str, project_id) -> dict:
    policy = project_access_policy(request, alias)
    members = project_member_rows(alias, project_id)
    can_manage = policy.can_manage_members(project_id)
    assignable_roles = set(policy.assignable_member_roles(project_id))
    for member in members:
        member["can_revoke"] = bool(can_manage and member["member_role"] in assignable_roles)

    roles_present = {row["member_role"] for row in members if row["membership_status"] == "active"}
    return {
        "project_members": members,
        "project_member_options": project_member_options(alias, project_id) if can_manage else [],
        "project_member_roles": [
            {"code": code, "label": MEMBER_ROLE_LABELS[code]}
            for code in policy.assignable_member_roles(project_id)
        ],
        "can_manage_project_members": can_manage,
        "can_edit_project": policy.can_edit_project(project_id),
        "can_webgis_write": policy.can_webgis_write(project_id),
        "project_has_pm": "project_manager" in roles_present,
        "project_has_leader": "project_leader" in roles_present,
    }


def _require_project(alias: str, project_id):
    project = Project.objects.using(alias).filter(pk=project_id).first()
    if not project:
        raise PermissionDenied("Project not found.")
    return project


@require_GET
def project_members_panel(request, pk):
    alias = require_tenant_context(request)
    project = _require_project(alias, pk)
    policy = project_access_policy(request, alias)
    if not policy.can_view(project.pk):
        raise PermissionDenied("Permission denied")
    context = {
        "project": project,
        **project_member_context(request, alias, project.pk),
    }
    return render(request, "geoflow_ops/projects/_project_members_panel.html", context)


@require_POST
def project_member_save(request, pk):
    alias = require_tenant_context(request)
    project = _require_project(alias, pk)
    policy = project_access_policy(request, alias)
    if not policy.can_manage_members(project.pk):
        raise PermissionDenied("Permission denied")
    if not _table_exists(alias, "prj.project_members"):
        return HttpResponseBadRequest("프로젝트 참여 기능이 아직 준비되지 않았습니다.")

    member_role = str(request.POST.get("member_role") or "").strip().lower()
    allowed_roles = set(policy.assignable_member_roles(project.pk))
    if member_role not in allowed_roles:
        raise PermissionDenied("해당 프로젝트 역할을 지정할 권한이 없습니다.")

    employee_id = _uuid(request.POST.get("employee_id"))
    if not employee_id:
        return HttpResponseBadRequest("직원 페이지에 등록된 참여자를 선택하세요.")

    with transaction.atomic(using=alias):
        with connections[alias].cursor() as cur:
            cur.execute(
                """
                SELECT 1
                  FROM hr.employee_profile
                 WHERE id=%s
                   AND COALESCE(status, '재직') <> '퇴사'
                 LIMIT 1
                """,
                [str(employee_id)],
            )
            if cur.fetchone() is None:
                return HttpResponseBadRequest("현재 프로젝트에 참여시킬 수 있는 직원을 찾을 수 없습니다.")

            if member_role in {"project_manager", "project_leader"}:
                cur.execute(
                    """
                    SELECT 1
                      FROM prj.project_members
                     WHERE project_id=%s
                       AND member_role=%s
                       AND membership_status='active'
                       AND employee_id <> %s
                     LIMIT 1
                    """,
                    [str(project.pk), member_role, str(employee_id)],
                )
                if cur.fetchone():
                    return HttpResponseBadRequest(
                        "Project Manager와 Project Leader는 프로젝트별 1명씩 지정합니다. 기존 담당자를 먼저 변경/해제하세요."
                    )

            cur.execute(
                """
                UPDATE prj.project_members
                   SET member_role=%s,
                       membership_status='active',
                       is_external=false,
                       invite_email=NULL,
                       invite_name=NULL,
                       updated_at=now()
                 WHERE project_id=%s
                   AND employee_id=%s
                   AND membership_status <> 'revoked'
             RETURNING id
                """,
                [member_role, str(project.pk), str(employee_id)],
            )
            row = cur.fetchone()
            if not row:
                cur.execute(
                    """
                    INSERT INTO prj.project_members
                        (project_id, employee_id, member_role, membership_status, is_external)
                    VALUES (%s, %s, %s, 'active', false)
                    """,
                    [str(project.pk), str(employee_id), member_role],
                )

    return redirect("tenant:project_detail", pk=project.pk)


@require_POST
def project_member_revoke(request, pk, member_id):
    alias = require_tenant_context(request)
    project = _require_project(alias, pk)
    policy = project_access_policy(request, alias)
    if not policy.can_manage_members(project.pk):
        raise PermissionDenied("Permission denied")
    if not _table_exists(alias, "prj.project_members"):
        return HttpResponseBadRequest("프로젝트 참여 기능이 아직 준비되지 않았습니다.")

    with transaction.atomic(using=alias):
        with connections[alias].cursor() as cur:
            cur.execute(
                """
                SELECT member_role
                  FROM prj.project_members
                 WHERE id=%s AND project_id=%s AND membership_status <> 'revoked'
                 FOR UPDATE
                """,
                [str(member_id), str(project.pk)],
            )
            row = cur.fetchone()
            if not row:
                return HttpResponseBadRequest("참여자를 찾을 수 없습니다.")
            if row[0] not in set(policy.assignable_member_roles(project.pk)):
                raise PermissionDenied("해당 역할의 참여자를 해제할 권한이 없습니다.")
            cur.execute(
                """
                UPDATE prj.project_members
                   SET membership_status='revoked', updated_at=now()
                 WHERE id=%s AND project_id=%s
                """,
                [str(member_id), str(project.pk)],
            )
    return redirect("tenant:project_detail", pk=project.pk)


@require_GET
def my_projects_api(request):
    """Return the project scope the current login may see; intended for WebGIS/QGIS clients."""
    alias = require_tenant_context(request)
    policy = project_access_policy(request, alias)
    queryset = Project.objects.using(alias).order_by("code", "name")
    visible_ids = policy.visible_project_ids()
    if visible_ids is not None:
        queryset = queryset.filter(pk__in=visible_ids)

    results = []
    for project in queryset:
        member = policy.membership(project.pk)
        results.append({
            "id": str(project.pk),
            "code": project.code or "",
            "name": project.name or "",
            "status": project.status or "",
            "member_role": member["member_role"] if member else None,
            "can_read": policy.can_webgis_read(project.pk),
            "can_write": policy.can_webgis_write(project.pk),
        })
    return JsonResponse({"results": results, "scope": policy.mode})


@require_GET
def project_access_api(request, pk):
    """Small authorization endpoint for WebGIS clients before loading project layers."""
    alias = require_tenant_context(request)
    project = _require_project(alias, pk)
    policy = project_access_policy(request, alias)
    if not policy.can_webgis_read(project.pk):
        raise PermissionDenied("Permission denied")
    member = policy.membership(project.pk)
    return JsonResponse({
        "project_id": str(project.pk),
        "member_role": member["member_role"] if member else None,
        "can_read": True,
        "can_write": policy.can_webgis_write(project.pk),
    })
