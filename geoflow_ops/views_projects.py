import os
import json
import re

# from __future__ import annotations
from typing import Any, Dict, List, Set, Tuple

from django.conf import settings
from django.contrib import messages
from django.db import connections, transaction
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST, require_http_methods
from django.views.generic import ListView
from django.contrib.auth.decorators import login_required

from control.services import central_repo as C   # 표준 접속/조회
from .models import Project, Contract, ProjectScopeItem
from control.catalog.models import CategoryNode, CategoryFacetOption, CategoryParent
from .forms import ProjectForm, ProjectNoteForm
from control.middleware import current_db_alias
from collections import defaultdict

from control.gf_authz.permissions import gf_perm_required
from control.gf_authz.query import gf_scope_queryset
from .views_catalog import build_scope_groups
from .views_project_members import project_member_context
from .services.project_access import project_access_policy
from .services.workflow_state import contract_workflow_summaries, contract_workflow_summary
from control.catalog import services_tenant as cat_svc
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP


def _alias(request):
    return current_db_alias()


class ProjectListView(ListView):
    model = Project
    template_name = "geoflow_ops/projects/project_list.html"
    context_object_name = "projects"
    paginate_by = None

    def get_queryset(self):
        alias = _alias(self.request)
        policy = project_access_policy(self.request, alias)
        queryset = (
            Project.objects.using(alias)
            .select_related(
                "contract",
                "contract__client",
                "contract__sub_client",
                "contract__org_unit"
            )
        )
        visible_ids = policy.visible_project_ids()
        if visible_ids is not None:
            queryset = queryset.filter(pk__in=visible_ids)
        return queryset.order_by("-contract__code", "contract__name")

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        alias = _alias(self.request)
        projects = list(self.object_list)
        contracts = [p.contract for p in projects if getattr(p, "contract", None)]
        summaries = contract_workflow_summaries(alias, contracts)
        counts = {"total": 0, "planned": 0, "active": 0, "pause": 0, "cancel": 0, "complete": 0}
        for project in projects:
            workflow = summaries.get(str(project.contract_id)) or contract_workflow_summary(alias, project.contract)
            project.contract_workflow = workflow
            counts["total"] += 1
            key = workflow.get("filter_key") or ""
            if key in counts:
                counts[key] += 1
        ctx["projects"] = projects
        ctx["status_counts"] = counts
        ctx["project_access"] = project_access_policy(self.request, alias)
        ctx["current_year"] = timezone.localdate().year
        return ctx


@login_required
@gf_perm_required("projects.view")
def project_list(request):
    return ProjectListView.as_view()(request)


@login_required
@gf_perm_required("projects.view")
def project_json(request, pk):
    alias = _alias(request)
    obj = (
        Project.objects.using(alias)
        .select_related(
            "contract",
            "contract__client",
            "contract__sub_client",
            "contract__org_unit",
        )
        .get(pk=pk)
    )
    policy = project_access_policy(request, alias)
    member = policy.membership(obj.pk)
    workflow = contract_workflow_summary(alias, obj.contract)
    d = {
        "project_id": str(obj.pk),
        "project_code": obj.code,
        "project_name": obj.name,
        "project_status": obj.status,
        "contract_code": obj.contract.code,
        "contract_name": obj.contract.name,
        "start_date": obj.contract.start_date.isoformat() if obj.contract.start_date else None,
        "end_date": obj.contract.end_date.isoformat() if obj.contract.end_date else None,
        "kind": obj.contract.kind,
        "client_name": (obj.contract.sub_client.name if obj.contract.kind == "하도급"
                        else (obj.contract.client.name if obj.contract.client else None)),
        "sub_client_name": obj.contract.sub_client.name if obj.contract.sub_client else None,
        "org_unit_name": obj.contract.org_unit.name if obj.contract.org_unit else None,
        "contract_workflow": workflow.get("major_code"),
        "contract_workflow_label": workflow.get("major_label"),
        "contract_complete": bool(workflow.get("is_complete")),
        "member_role": member["member_role"] if member else None,
        "can_edit_project": policy.can_edit_project(obj.pk),
        "can_webgis_write": policy.can_webgis_write(obj.pk),
    }
    return JsonResponse(d)


from .forms import ProjectNoteForm


@gf_perm_required("projects.view")
def project_detail_page(request, pk):
    alias = _alias(request)
    obj = get_object_or_404(
        Project.objects.using(alias).select_related(
            "contract", "contract__client", "contract__sub_client", "contract__org_unit",
        ),
        pk=pk,
    )
    policy = project_access_policy(request, alias)
    member_ctx = project_member_context(request, alias, obj.pk)
    contract_workflow = contract_workflow_summary(alias, obj.contract)

    if request.method == "POST":
        form = ProjectNoteForm(request.POST, instance=obj)
        if form.is_valid():
            inst = form.save(commit=False)
            inst.contract_id = obj.contract_id
            inst.save(using=alias, update_fields=["description", "updated_at"])
            messages.success(request, "저장했습니다.")
            return redirect("tenant:project_detail", pk=obj.pk)

        errors_json = form.errors.get_json_data()
        flat_errors = [e["message"] for _, errs in errors_json.items() for e in errs]
        context = {
            "obj": obj,
            "edit_mode": True,
            "form": form,
            "errors": flat_errors,
            "scope_groups": build_scope_groups(alias, obj.pk),
            "project_access": policy,
            "contract_workflow": contract_workflow,
            **member_ctx,
        }
        return render(request, "geoflow_ops/projects/project_detail.html", context)

    requested_edit = str(request.GET.get("edit", "")).lower() in ("1", "true", "yes")
    edit_mode = bool(requested_edit and policy.can_edit_project(obj.pk))
    context = {
        "obj": obj,
        "edit_mode": edit_mode,
        "project_access": policy,
        "contract_workflow": contract_workflow,
        **member_ctx,
    }
    if edit_mode:
        context["form"] = ProjectNoteForm(instance=obj)

    context["scope_groups"] = build_scope_groups(alias, obj.pk)
    return render(request, "geoflow_ops/projects/project_detail.html", context)


# :::::::::: CATALOG 관련 ::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::::

def _to_decimal(v):
    if v in (None, "", "null"):
        return None
    try:
        return Decimal(str(v))
    except (InvalidOperation, ValueError):
        return None


@login_required
@gf_perm_required("projects.edit")
def project_summary(request, pk):
    alias = _alias(request)
    prj = get_object_or_404(Project.objects.using(alias), pk=pk)
    scope_groups = build_scope_groups(alias, prj.pk)
    return render(request, "geoflow_ops/projects/project_summary.html", {
        "project": prj,
        "scope_groups": scope_groups,
    })


@login_required
@gf_perm_required("projects.edit")
@require_http_methods(["POST"])
@transaction.atomic
def project_summary_save(request, pk):
    """
    project_summary.html 모달에서 오는 폼 POST 저장:
    - name="rows[<키>][progress|completed|note|l2_code|l3_code|item_id]"
    - <키>는 기존 item_id(uuids) 또는 "L2CODE|L3CODE" 형태
    """
    alias = _alias(request)
    project = get_object_or_404(Project.objects.using(alias), pk=pk)

    row_re = re.compile(r"^rows\[(.+?)\]\[(\w+)\]$")
    rows: Dict[str, Dict[str, str]] = {}
    for k, v in request.POST.items():
        m = row_re.match(k)
        if not m:
            continue
        key, field = m.group(1), m.group(2)
        rows.setdefault(key, {})[field] = v

    def to_decimal(val):
        if val in (None, "", "null"):
            return None
        try:
            return Decimal(str(val))
        except (InvalidOperation, ValueError, TypeError):
            return None

    central = cat_svc.CENTRAL_ALIAS

    for key, data in rows.items():
        item_id = data.get("item_id")
        l2_code = data.get("l2_code")
        l3_code = data.get("l3_code")

        progress_raw = data.get("progress", None)
        completed_raw = data.get("completed", None)
        note_raw = data.get("note", None)

        progress_is_set = "progress" in data
        completed_is_set = "completed" in data
        note_is_set = "note" in data

        progress = to_decimal(progress_raw)
        completed = to_decimal(completed_raw)
        note = (note_raw.strip() or None) if isinstance(note_raw, str) else None

        if item_id:
            try:
                psi = ProjectScopeItem.objects.using(alias).get(pk=item_id, project_id=project.pk)
            except ProjectScopeItem.DoesNotExist:
                continue

            update_fields: List[str] = []

            if hasattr(psi, "progress_qty") and progress_is_set:
                psi.progress_qty = progress
                update_fields.append("progress_qty")

            if completed_is_set:
                psi.completed_qty = completed
                update_fields.append("completed_qty")

            if hasattr(psi, "note") and note_is_set:
                psi.note = note
                update_fields.append("note")

            if update_fields:
                psi.save(update_fields=update_fields)
            continue

        if not (l2_code and l3_code):
            if "|" in key:
                l2_code, l3_code = key.split("|", 1)
            if not (l2_code and l3_code):
                continue

        l2 = CategoryNode.objects.using(central).filter(code=l2_code).first()
        l3 = CategoryFacetOption.objects.using(central).filter(code=l3_code).first()
        if not l2 or not l3:
            continue

        base = {
            "project_id": project.pk,
            "lv2_id": str(l2.id),
            "lv3_id": str(l3.id),
            "lv4_id": None,
        }

        defaults: Dict[str, Any] = {}
        if hasattr(ProjectScopeItem, "progress_qty") and progress_is_set:
            defaults["progress_qty"] = progress
        if completed_is_set:
            defaults["completed_qty"] = completed
        if hasattr(ProjectScopeItem, "note") and note_is_set:
            defaults["note"] = note

        if defaults:
            ProjectScopeItem.objects.using(alias).update_or_create(**base, defaults=defaults)

    messages.success(request, "현재 업무를 저장했습니다.")
    return redirect("tenant:project_summary", pk=project.pk)
