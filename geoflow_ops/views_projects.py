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
from .forms import ProjectForm
from django.core.exceptions import ValidationError, PermissionDenied
from django.db.models.functions import Coalesce
from django.db.models import F
from control.gf_authz.permissions import gf_has_perm
from .services.contract_project_pair import create_project, save_project
from .services.project_status import project_status_options, status_key
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
        contract_id = self.request.GET.get("contract")
        if contract_id:
            try:
                from uuid import UUID
                queryset = queryset.filter(contract_id=UUID(contract_id))
            except ValueError:
                queryset = queryset.none()
        queryset = queryset.annotate(modified_order=Coalesce("updated_at", "created_at")).order_by(F("modified_order").desc(nulls_last=True), "id")
        if self.request.GET.get("overview") == "1":
            from .services.dashboard import workflow_map, filter_records
            rows = list(queryset)
            summaries = workflow_map(self.request, alias, [p.contract for p in rows if p.contract_id])
            return filter_records(rows, summaries, self.request.GET, projects=True)
        return queryset

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        alias = _alias(self.request)
        projects = list(self.object_list)
        labels = dict(project_status_options(alias))
        counts = {"total": len(projects), "planned": 0, "active": 0, "pause": 0, "cancel": 0, "complete": 0}
        from .views_dashboard import _project_managers
        managers = _project_managers(alias, [str(p.pk) for p in projects]) if gf_has_perm(self.request, "directory.view") else {}
        for project in projects:
            project.manager_names = managers.get(str(project.pk), "미지정") if gf_has_perm(self.request, "directory.view") else "열람 제한"
            project.status_label = labels.get(project.status, project.status or "미설정")
            project.status_key = status_key(project.status)
            if project.status_key in counts:
                counts[project.status_key] += 1
        policy = project_access_policy(self.request, alias)
        ctx["can_create_project"] = policy.can_edit_all and gf_has_perm(self.request, "projects.edit") and gf_has_perm(self.request, "contracts.view")
        # Filter choices derive only from projects the current user can see.
        visible = Project.objects.using(alias).select_related("contract")
        ids = policy.visible_project_ids()
        if ids is not None:
            visible = visible.filter(pk__in=ids)
        ctx["contract_options"] = sorted({str(p.contract_id): p.contract for p in visible if p.contract_id}.values(), key=lambda c: (c.code or "", str(c.pk)), reverse=True)
        ctx["selected_contract"] = self.request.GET.get("contract", "")
        ctx["projects"] = projects
        ctx["status_counts"] = counts
        ctx["project_access"] = project_access_policy(self.request, alias)
        ctx["current_year"] = timezone.localdate().year
        return ctx


def project_create(request):
    alias = _alias(request)
    contracts = Contract.objects.using(alias).order_by("-code", "id")
    initial = {"status": "active"}
    if request.GET.get("contract"):
        from uuid import UUID
        try:
            contract = get_object_or_404(contracts, pk=UUID(request.GET["contract"]))
        except ValueError:
            from django.http import Http404
            raise Http404
        initial.update(contract=contract.pk, name=contract.name if (contract.ext or {}).get("project_mode") == "SINGLE" else "",
                       start_date=contract.start_date, end_date=contract.end_date)
    form = ProjectForm(request.POST if request.method == "POST" else None, alias=alias, contracts=contracts, initial=initial)
    if request.method == "POST" and form.is_valid():
        try:
            obj = create_project(alias, form.cleaned_data["contract"].pk, form.cleaned_data,
                                 allow_duplicate=form.cleaned_data["confirm_duplicate"])
        except ValidationError as exc:
            form.add_error(None, exc)
        else:
            messages.success(request, "프로젝트를 생성했습니다.")
            return redirect("tenant:project_detail", pk=obj.pk)
    return render(request, "geoflow_ops/projects/project_form.html", {"form": form, "contract_names": {str(c.pk): {"name": c.name, "single": (c.ext or {}).get("project_mode") == "SINGLE"} for c in contracts}})


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
    workflow = contract_workflow_summary(alias, obj.contract, request=request)
    d = {
        "project_id": str(obj.pk),
        "project_code": obj.code,
        "project_name": obj.name,
        "project_status": obj.status,
        "contract_code": obj.contract.code,
        "contract_name": obj.contract.name,
        "start_date": obj.start_date.isoformat() if obj.start_date else None,
        "end_date": obj.end_date.isoformat() if obj.end_date else None,
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
    obj.status_label = dict(project_status_options(alias)).get(obj.status, obj.status or "미설정")
    contract_workflow = contract_workflow_summary(alias, obj.contract, request=request)

    if request.method == "POST":
        if not policy.can_edit_project(obj.pk):
            raise PermissionDenied("Permission denied")
        form = ProjectForm(request.POST, instance=obj, alias=alias)
        if form.is_valid():
            try:
                save_project(alias, obj.pk, form.cleaned_data, allow_duplicate=form.cleaned_data["confirm_duplicate"])
            except ValidationError as exc:
                form.add_error(None, exc)
            else:
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
        context["form"] = ProjectForm(instance=obj, alias=alias)

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
