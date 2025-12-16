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
        return (
            Project.objects.using(alias)
            .select_related(
                "contract",
                "contract__client",
                "contract__sub_client",
                "contract__org_unit"
            )
            .order_by("-contract__code", "contract__name")
        )
    
    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        # self.object_list 는 get_queryset() 이후 이미 채워짐
        counts = {"total": 0, "planned": 0, "active": 0, "pause": 0, "cancel": 0, "complete": 0}
        syn = {
            "planned": {"planned"},
            "active": {"active"},
            "pause": {"pause", "paused"},
            "cancel": {"cancel", "canceled"},
            "complete": {"complete", "completed"},
        }
        for p in self.object_list:
            s = (getattr(p.contract, "status", "") or "").lower()
            counts["total"] += 1
            if   s in syn["planned"]:  counts["planned"]  += 1
            elif s in syn["active"]:   counts["active"]   += 1
            elif s in syn["pause"]:    counts["pause"]    += 1
            elif s in syn["cancel"]:   counts["cancel"]   += 1
            elif s in syn["complete"]: counts["complete"] += 1
        ctx["status_counts"] = counts
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
        Project.objects.using(_alias(request))
        .select_related(
            "contract",
            "contract__client",
            "contract__sub_client",
            "contract__org_unit",
        )
        .get(pk=pk)
    )
    d = {
        "contract_code": obj.contract.code,
        "contract_name": obj.contract.name,
        "start_date": obj.contract.start_date.isoformat() if obj.contract.start_date else None,
        "end_date": obj.contract.end_date.isoformat() if obj.contract.end_date else None,
        "kind": obj.contract.kind,
        "client_name": (obj.contract.sub_client.name if obj.contract.kind == "하도급"
                        else (obj.contract.client.name if obj.contract.client else None)),
        "sub_client_name": obj.contract.sub_client.name if obj.contract.sub_client else None,
        "org_unit_name": obj.contract.org_unit.name if obj.contract.org_unit else None,
        "status": obj.contract.status,
    }
    return JsonResponse(d)


# views_projects.py
from .forms import ProjectNoteForm  # ← 새 폼 임포트

@gf_perm_required("projects.view")
def project_detail_page(request, pk):
    alias = _alias(request)
    obj = get_object_or_404(
        Project.objects.using(alias).select_related(
            "contract", "contract__client", "contract__sub_client", "contract__org_unit",
        ),
        pk=pk,
    )

    # --- POST: 비고만 저장 ---
    if request.method == "POST":
        form = ProjectNoteForm(request.POST, instance=obj)
        if form.is_valid():
            inst = form.save(commit=False)
            # 안전장치: 혹시라도 폼에 contract가 추가되더라도 기존 값을 유지
            inst.contract_id = obj.contract_id
            inst.save(using=alias, update_fields=["description", "updated_at"])
            messages.success(request, "저장했습니다.")
            return redirect("tenant:project_detail", pk=obj.pk)

        errors_json = form.errors.get_json_data()
        flat_errors = [e["message"] for _, errs in errors_json.items() for e in errs]
        return render(
            request,
            "geoflow_ops/projects/project_detail.html",
            {"obj": obj, "edit_mode": True, "form": form, "errors": flat_errors},
        )

    # --- GET ---
    edit_mode = str(request.GET.get("edit", "")).lower() in ("1", "true", "yes")
    context = {"obj": obj, "edit_mode": edit_mode}
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

    # 1) rows[...] 묶음 파싱
    row_re = re.compile(r"^rows\[(.+?)\]\[(\w+)\]$")
    rows: Dict[str, Dict[str, str]] = {}
    for k, v in request.POST.items():
        m = row_re.match(k)
        if not m:
            continue
        key, field = m.group(1), m.group(2)  # key: item_id 또는 "L2CODE|L3CODE"
        rows.setdefault(key, {})[field] = v

    # 2) 숫자 변환
    def to_decimal(val):
        if val in (None, "", "null"):
            return None
        try:
            return Decimal(str(val))
        except (InvalidOperation, ValueError, TypeError):
            return None

    central = cat_svc.CENTRAL_ALIAS

    # 3) 각 행 저장 (이번 수정의 핵심: "제출 여부"를 기준으로 저장하므로 None도 저장)
    for key, data in rows.items():
        item_id = data.get("item_id")  # 있으면 기존 항목
        l2_code = data.get("l2_code")
        l3_code = data.get("l3_code")

        # 원본 문자열 및 "제출 여부" 플래그
        progress_raw  = data.get("progress", None)
        completed_raw = data.get("completed", None)
        note_raw      = data.get("note", None)

        progress_is_set  = ("progress"  in data)  # 제출만 됐으면 None도 저장
        completed_is_set = ("completed" in data)
        note_is_set      = ("note"      in data)

        # 값 변환(숫자 or None)
        progress  = to_decimal(progress_raw)
        completed = to_decimal(completed_raw)
        note      = (note_raw.strip() or None) if isinstance(note_raw, str) else None

        # (A) 기존 항목이면 id로 갱신
        if item_id:
            try:
                psi = ProjectScopeItem.objects.using(alias).get(pk=item_id, project_id=project.pk)
            except ProjectScopeItem.DoesNotExist:
                continue

            update_fields: List[str] = []

            if hasattr(psi, "progress_qty") and progress_is_set:
                psi.progress_qty = progress          # None 포함 저장
                update_fields.append("progress_qty")

            if completed_is_set:
                psi.completed_qty = completed        # None 포함 저장
                update_fields.append("completed_qty")

            if hasattr(psi, "note") and note_is_set:
                psi.note = note                      # None 포함 저장
                update_fields.append("note")

            if update_fields:
                psi.save(update_fields=update_fields)
            continue

        # (B) 신규/코드 기반 저장: "L2CODE|L3CODE" → 중앙에서 id 매핑
        if not (l2_code and l3_code):
            # key가 "L2CODE|L3CODE" 형태인 경우 split
            if "|" in key:
                l2_code, l3_code = key.split("|", 1)
            if not (l2_code and l3_code):
                continue

        l2 = CategoryNode.objects.using(central).filter(code=l2_code).first()
        l3 = CategoryFacetOption.objects.using(central).filter(code=l3_code).first()
        if not l2 or not l3:
            continue  # 잘못된 코드면 스킵

        base = {
            "project_id": project.pk,
            "lv2_id": str(l2.id),
            "lv3_id": str(l3.id),
            "lv4_id": None,
        }

        # defaults는 "제출된 필드만" 포함 (None도 값으로 저장됨)
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
    # 모달 제출은 AJAX로 가로채므로 리다이렉트 응답을 반환해도 OK
    return redirect("tenant:project_summary", pk=project.pk)
