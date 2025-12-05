import os
import json

# from __future__ import annotations
from typing import Any, Dict, List, Set, Tuple

from django.conf import settings
from django.contrib import messages
from django.db import connections
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST
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
from.views_catalog import build_scope_groups
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



