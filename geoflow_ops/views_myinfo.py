from __future__ import annotations

from uuid import UUID, uuid4

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import connections, transaction
from django.http import HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render

from geoflow_ops.forms import MyOrgUnitForm
from geoflow_ops.models import MyOrgUnit
from geoflow_ops.services.hr_masters import (
    MASTER_FIELD_REFS,
    list_master_options,
    master_table_exists,
)
from geoflow_ops.views_contracts import _alias


def _uuid_or_none(value):
    if value in (None, ""):
        return None
    try:
        return UUID(str(value))
    except (TypeError, ValueError, AttributeError):
        return None


def _column_exists(alias: str, schema: str, table: str, column: str) -> bool:
    with connections[alias].cursor() as cur:
        cur.execute(
            """
            SELECT 1
              FROM information_schema.columns
             WHERE table_schema=%s AND table_name=%s AND column_name=%s
             LIMIT 1
            """,
            [schema, table, column],
        )
        return cur.fetchone() is not None


def _load_departments(alias: str, org_unit_id):
    with connections[alias].cursor() as cur:
        cur.execute(
            """
            SELECT id::text, name, active
              FROM hr.departments
             WHERE org_unit_id=%s
             ORDER BY name, id
            """,
            [str(org_unit_id)],
        )
        rows = cur.fetchall()
    return [
        {"id": row[0], "name": row[1] or "", "active": bool(row[2])}
        for row in rows
    ]


def _load_master(alias: str, category: str):
    if not master_table_exists(alias, category):
        return []
    return list_master_options(alias, category, active_only=False)


@login_required
def orgunit_list(request):
    alias = _alias(request)
    qs = MyOrgUnit.objects.using(alias).all().order_by("name")
    return render(request, "geoflow_ops/myinfo/orgunit_list.html", {"items": qs})


@login_required
def orgunit_detail(request, pk):
    alias = _alias(request)
    obj = get_object_or_404(MyOrgUnit.objects.using(alias), pk=pk)
    return render(
        request,
        "geoflow_ops/myinfo/orgunit_detail.html",
        {
            "obj": obj,
            "departments": _load_departments(alias, obj.pk),
            "job_grades": _load_master(alias, "position_grade"),
            "job_positions": _load_master(alias, "position_title"),
        },
    )


@login_required
def orgunit_create(request):
    alias = _alias(request)
    if request.method == "POST":
        form = MyOrgUnitForm(request.POST)
        if form.is_valid():
            obj = form.save(commit=False)
            obj.save(using=alias)
            messages.success(request, "회사 정보를 추가했습니다.")
            return redirect("tenant:myinfo_orgunit_detail", pk=obj.pk)
    else:
        form = MyOrgUnitForm()

    return render(
        request,
        "geoflow_ops/myinfo/orgunit_form.html",
        {"form": form, "mode": "create"},
    )


@login_required
def orgunit_update(request, pk):
    alias = _alias(request)
    obj = get_object_or_404(MyOrgUnit.objects.using(alias), pk=pk)

    if request.method == "POST":
        form = MyOrgUnitForm(request.POST, instance=obj)
        if form.is_valid():
            obj = form.save(commit=False)
            obj.save(using=alias)
            messages.success(request, "회사 정보를 수정했습니다.")
            return redirect("tenant:myinfo_orgunit_detail", pk=obj.pk)
    else:
        form = MyOrgUnitForm(instance=obj)

    return render(
        request,
        "geoflow_ops/myinfo/orgunit_form.html",
        {"form": form, "mode": "edit", "obj": obj},
    )


@login_required
def orgunit_department_save(request, pk):
    alias = _alias(request)
    obj = get_object_or_404(MyOrgUnit.objects.using(alias), pk=pk)
    department_id = _uuid_or_none(request.POST.get("department_id"))
    name = str(request.POST.get("name") or "").strip()
    active = str(request.POST.get("active") or "").lower() in {"1", "true", "yes", "on"}
    if not name:
        return HttpResponseBadRequest("부서명을 입력하세요.")

    with transaction.atomic(using=alias):
        with connections[alias].cursor() as cur:
            cur.execute(
                """
                SELECT id::text
                  FROM hr.departments
                 WHERE org_unit_id=%s AND lower(name)=lower(%s)
                   AND (%s::uuid IS NULL OR id<>%s::uuid)
                 LIMIT 1
                """,
                [
                    str(obj.pk),
                    name,
                    str(department_id) if department_id else None,
                    str(department_id) if department_id else None,
                ],
            )
            if cur.fetchone():
                return HttpResponseBadRequest("같은 회사에 동일한 부서가 이미 있습니다.")

            if department_id:
                cur.execute(
                    """
                    UPDATE hr.departments
                       SET name=%s, active=%s, updated_at=now()
                     WHERE id=%s AND org_unit_id=%s
                    """,
                    [name, active, str(department_id), str(obj.pk)],
                )
                if cur.rowcount != 1:
                    return HttpResponseBadRequest("부서를 찾을 수 없습니다.")
                messages.success(request, "부서를 수정했습니다.")
            else:
                legacy_code_column = _column_exists(alias, "hr", "departments", "code")
                if legacy_code_column:
                    cur.execute(
                        """
                        INSERT INTO hr.departments (org_unit_id, code, name, active)
                        VALUES (%s, %s, %s, %s)
                        """,
                        [str(obj.pk), f"dept-{uuid4().hex}", name, active],
                    )
                else:
                    cur.execute(
                        "INSERT INTO hr.departments (org_unit_id, name, active) VALUES (%s, %s, %s)",
                        [str(obj.pk), name, active],
                    )
                messages.success(request, "부서를 추가했습니다.")

    return redirect("tenant:myinfo_orgunit_detail", pk=obj.pk)


def _master_save(request, pk, *, category: str, label: str, prefix: str):
    alias = _alias(request)
    obj = get_object_or_404(MyOrgUnit.objects.using(alias), pk=pk)
    field_ref = MASTER_FIELD_REFS[category]
    employee_column = {
        "position_grade": "position_grade",
        "position_title": "title",
    }[category]
    if not master_table_exists(alias, category):
        return HttpResponseBadRequest(f"{label} 마스터가 아직 준비되지 않았습니다.")

    master_id = _uuid_or_none(request.POST.get("master_id"))
    active = str(request.POST.get("active") or "").lower() in {"1", "true", "yes", "on"}
    name = str(request.POST.get("name") or "").strip()

    with transaction.atomic(using=alias):
        with connections[alias].cursor() as cur:
            if master_id:
                cur.execute("SELECT name FROM ops.settings_nodes WHERE id=%s FOR UPDATE", [str(master_id)])
                row = cur.fetchone()
                if not row:
                    return HttpResponseBadRequest(f"{label} 항목을 찾을 수 없습니다.")
                master_name = str(row[0] or "").strip()
                if not active:
                    cur.execute(
                        f"""
                        SELECT COUNT(*)
                          FROM hr.employee_profile
                         WHERE lower(btrim(COALESCE({employee_column}, ''))) = lower(%s)
                        """,
                        [master_name],
                    )
                    assigned_count = int(cur.fetchone()[0] or 0)
                    if assigned_count:
                        return HttpResponseBadRequest(
                            f"현재 {assigned_count}명의 직원이 사용하는 {label}입니다. "
                            f"직원 정보를 먼저 변경한 뒤 사용 중지하세요."
                        )
                cur.execute("UPDATE ops.settings_nodes SET active=%s, updated_at=now() WHERE id=%s", [active, str(master_id)])
                messages.success(request, f"{label} 사용 여부를 변경했습니다.")
            else:
                if not name:
                    return HttpResponseBadRequest(f"추가할 {label}명을 입력하세요.")
                cur.execute(
                    """SELECT 1 FROM ops.settings_nodes child
                         JOIN ops.settings_nodes category ON category.id=child.parent_id
                        WHERE category.field_ref=%s AND lower(child.name)=lower(%s) LIMIT 1""",
                    [field_ref, name],
                )
                if cur.fetchone():
                    return HttpResponseBadRequest(f"동일한 {label}이 이미 있습니다.")
                cur.execute(
                    """SELECT COALESCE(MAX(child.ord), 0) + 10
                         FROM ops.settings_nodes category
                         LEFT JOIN ops.settings_nodes child ON child.parent_id=category.id
                        WHERE category.field_ref=%s""",
                    [field_ref],
                )
                ord_value = int(cur.fetchone()[0] or 10)
                cur.execute(
                    """INSERT INTO ops.settings_nodes
                           (parent_id, code, name, node_type, ord, active, locked)
                         SELECT id, %s, %s, 'value', %s, true, false
                           FROM ops.settings_nodes WHERE field_ref=%s""",
                    [f"legacy-{uuid4().hex}", name, ord_value, field_ref],
                )
                messages.success(request, f"{label}을 추가했습니다.")

    return redirect("tenant:myinfo_orgunit_detail", pk=obj.pk)


@login_required
def job_grade_save(request, pk):
    return _master_save(
        request,
        pk,
        category="position_grade",
        label="직급",
        prefix="grade",
    )


@login_required
def job_position_save(request, pk):
    return _master_save(
        request,
        pk,
        category="position_title",
        label="직위",
        prefix="position",
    )
