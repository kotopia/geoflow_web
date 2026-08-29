# geoflow_ops/views_contracts.py
from __future__ import annotations
import os
from uuid import uuid4
import json
import logging, time
from pprint import pformat

from typing import Any

from django.conf import settings
from django.contrib import messages
from django.db import connections, transaction, IntegrityError
from django.db.models import Q, Count
from django.http import JsonResponse, Http404, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST, require_GET, require_http_methods
from django.views.generic import ListView

from control.services import central_repo as C   # 표준 접속/조회
from control.middleware import current_db_alias
from .models import Contract, Partner, Project, MyOrgUnit, Attachment
from .forms import ContractForm, PartnerForm
from .views_catalog import build_scope_groups  # ← 프로젝트 범위 SSR용


from .utils.ctr_utils import next_contract_code

from control.gf_authz.permissions import gf_has_perm, gf_perm_required
from control.gf_authz.query import gf_scope_queryset

# from .services.contract_utils import next_contract_code

logger = logging.getLogger(__name__)


def _post_snapshot(request, keys=None, limit=200):
    keys = keys or ["code","name","start_date","end_date","amount","client","sub_client","org_unit"]
    snap = {}
    for k in keys:
        v = request.POST.get(k)
        if v is None:
            continue
        s = str(v)
        snap[k] = s if len(s) <= limit else s[:limit] + "...(+trunc)"
    return snap



import pprint
pp = pprint.PrettyPrinter(indent=2)


def _alias(request):
    return current_db_alias()

# -------------------------
# 계약 리스트/상세/생성
# -------------------------
class ContractListView(ListView):
    model = Contract
    template_name = "geoflow_ops/contracts/contract_list.html"
    context_object_name = "contracts"
    paginate_by = None

    def get_queryset(self):
        alias = _alias(self.request)
        return (
            Contract.objects.using(alias)
            .select_related("client", "sub_client", "org_unit")
            .all()
            .order_by("-code", "name")
        )
    
    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        # Contract lifecycle counts are rendered from the event-derived workflow
        # rows in the list UI. Legacy Contract.status is intentionally ignored.
        ctx["entity"] = "contract"
        ctx["current_year"] = timezone.localdate().year
        return ctx

@gf_perm_required("contracts.view")
def contract_list(request):
    return ContractListView.as_view()(request)


@login_required
@gf_perm_required("contracts.view")
def contract_detail_page(request, pk):
    if request.method == "POST" and not gf_has_perm(request, "contracts.edit"):
        return HttpResponseForbidden("Permission denied")

    alias = _alias(request)
    logger.info("contract detail read")
    obj = get_object_or_404(Contract.objects.using(alias), pk=pk)

    # 연관 파트너 표시용(보기/편집 공통)
    client_name, subclient_name = None, None
    if getattr(obj, "client_id", None):
        p = Partner.objects.using(alias).filter(id=obj.client_id).first()
        client_name = p.name if p else None
    if getattr(obj, "sub_client_id", None):
        p = Partner.objects.using(alias).filter(id=obj.sub_client_id).first()
        subclient_name = p.name if p else None

    # ----- POST: 편집 저장 -----
    if request.method == "POST":
        form = ContractForm(request.POST, instance=obj)

        # ✅ 중요: 폼 검증 전에 alias-aware 쿼리셋 주입
        if "client" in form.fields:
            form.fields["client"].queryset = Partner.objects.using(alias).all()
        if "sub_client" in form.fields:
            form.fields["sub_client"].queryset = Partner.objects.using(alias).all()
        if "org_unit" in form.fields:
            form.fields["org_unit"].queryset = MyOrgUnit.objects.using(alias).all()

        logger.info("contract detail update request")
        if form.is_valid():
            inst = form.save(commit=False)
            inst.updated_at = timezone.now()
            if inst.ext is None:
                inst.ext = {}
            inst.save(using=alias)
            logger.info("contract detail update processed")
            messages.success(request, "저장했습니다.")
            return redirect("tenant:contract_detail", pk=obj.pk)

        # ❗검증 실패: 편집 모드로 재렌더 + 에러 메시지 전달
        errors_json = form.errors.get_json_data()
        flat_errors = [e["message"] for _, errs in errors_json.items() for e in errs]
        logger.warning("contract form validation failed")
        return render(
            request,
            "geoflow_ops/contracts/contract_detail.html",
            {
                "obj": obj,
                "client_name": client_name or "-",
                "subclient_name": subclient_name or "-",
                "edit_mode": True,
                "form": form,
                "errors": flat_errors,  # ← 추가: 화면에 이유가 보입니다
                "client_selected": form["client"].value() or "",
                "subclient_selected": form["sub_client"].value() or "",
            },
        )

    # ----- GET: 보기/편집 모드 진입 -----
    edit_mode = str(request.GET.get("edit", "")).lower() in ("1", "true", "yes")
    context = {
        "obj": obj,
        "client_name": client_name or "-",
        "subclient_name": subclient_name or "-",
        "edit_mode": edit_mode,
    }

    # 🔹 (추가) 이 계약과 연결된 프로젝트 1건 + 범위 그룹(SSR용)
    prj = Project.objects.using(alias).filter(contract=obj).first()
    context["project_for_scope"] = prj
    context["scope_groups"] = build_scope_groups(alias, prj.id) if prj else []

    # 계약 첨부파일 목록 (삭제되지 않은 것만)
    attachments = Attachment.objects.using(alias).filter(
        entity_type="contract",
        entity_id=obj.id,
        active=True,
        deleted_at__isnull=True,
    ).order_by("purpose", "ord", "-created_at")
    context["attachments"] = list(attachments)

    if edit_mode:
        form = ContractForm(instance=obj)
        # ✅ 권장: 편집 폼의 선택지도 alias에 맞추기
        if "client" in form.fields:
            form.fields["client"].queryset = Partner.objects.using(alias).all()
        if "sub_client" in form.fields:
            form.fields["sub_client"].queryset = Partner.objects.using(alias).all()
        if "org_unit" in form.fields:
            form.fields["org_unit"].queryset = MyOrgUnit.objects.using(alias).all()

        context.update({
            "form": form,
            "client_selected": obj.client_id or "",
            "subclient_selected": getattr(obj, "sub_client_id", "") or "",
        })

    return render(request, "geoflow_ops/contracts/contract_detail.html", context)

@require_GET
def contract_json(request, pk):
    alias = _alias(request)
    obj = get_object_or_404(
        Contract.objects.using(alias).select_related("client", "sub_client", "org_unit"),
        pk=pk,
    )

    client_name = None
    subclient_name = None
    if getattr(obj, "client_id", None):
        p = Partner.objects.using(alias).filter(id=obj.client_id).first()
        client_name = p.name if p else None
    if getattr(obj, "sub_client_id", None):
        p = Partner.objects.using(alias).filter(id=obj.sub_client_id).first()
        subclient_name = p.name if p else None

    org_unit_name = None
    if getattr(obj, "org_unit_id", None):
        # select_related를 썼으면 obj.org_unit.name으로 바로 가능
        try:
            org_unit_name = obj.org_unit.name
        except MyOrgUnit.DoesNotExist:
            org_unit_name = None

    return JsonResponse({
        "id": str(obj.id),
        "code": getattr(obj, "code", None),
        "name": getattr(obj, "name", None),
        "start_date": (obj.start_date.isoformat() if getattr(obj, "start_date", None) else None),
        "end_date": (obj.end_date.isoformat() if getattr(obj, "end_date", None) else None),
        "amount": getattr(obj, "amount", None),
        "client_name": client_name,
        "sub_client_name": subclient_name,
        "org_unit_name": org_unit_name,
    })


def event_modal_ui(request):
    scope_type = request.GET.get("scope_type", "")
    scope_id = request.GET.get("scope_id", "")
    return render(
        request,
        "geoflow_ops/events/_event_modal.html",
        {
            "scope_type": scope_type,
            "scope_id": scope_id,
        },
    )


@login_required
@gf_perm_required("contracts.create")
@require_http_methods(["GET", "POST"])
def contract_create(request):
    alias = _alias(request)

    # ---------------------- GET: 새 계약 화면 ----------------------
    if request.method == "GET":
        initial_code = next_contract_code(alias)
        form = ContractForm(initial={"code": initial_code})
        if "client" in form.fields:
            form.fields["client"].queryset = Partner.objects.using(alias).all()
        if "sub_client" in form.fields:
            form.fields["sub_client"].queryset = Partner.objects.using(alias).all()
        if "org_unit" in form.fields:
            form.fields["org_unit"].queryset = MyOrgUnit.objects.using(alias).all()
        return render(
            request,
            "geoflow_ops/contracts/contract_detail.html",
            {
                "obj": None,
                "form": form,
                "edit_mode": True,
                "force_create": True,   # 사용 중이면 유지
                "errors": [],
                "client_selected": None,
                "subclient_selected": None,
            },
        )

    # ---------------------- POST: 저장 처리 ----------------------
    form = ContractForm(request.POST)
    if "client" in form.fields:
        form.fields["client"].queryset = Partner.objects.using(alias).all()
    if "sub_client" in form.fields:
        form.fields["sub_client"].queryset = Partner.objects.using(alias).all()
    if "org_unit" in form.fields:
        form.fields["org_unit"].queryset = MyOrgUnit.objects.using(alias).all()
        
    if not form.is_valid():
        # 에러 메시지 평탄화(선택)
        errors_json = form.errors.get_json_data()
        flat_errors = [e["message"] for _, errs in errors_json.items() for e in errs]
        return render(
            request,
            "geoflow_ops/contracts/contract_detail.html",
            {
                "obj": None,
                "form": form,
                "edit_mode": True,
                "force_create": True,
                "errors": flat_errors,
                "client_selected": request.POST.get("client"),
                "subclient_selected": request.POST.get("sub_client"),
            },
        )

    # 유효하면 저장
    obj = form.save(commit=False)
    now = timezone.now()
    if not getattr(obj, "created_at", None):
        obj.created_at = now
    obj.updated_at = now
    if hasattr(obj, "ext") and getattr(obj, "ext", None) is None:
        obj.ext = {}

    try:
        with transaction.atomic(using=alias):
            obj.save(using=alias)

            # (선택) 프로젝트 자동 생성/동기화가 기존에 있었다면 유지
            # try:
            #     proj = Project.objects.using(alias).filter(contract=obj).first()
            #     if not proj:
            #         Project.objects.using(alias).create(
            #             contract=obj,
            #             code=f"C{str(obj.code).replace('-', '')}",
            #             name=obj.name,
            #             start_date=obj.start_date,
            #             end_date=obj.end_date,
            #             status="active",
            #             ext={} if hasattr(Project, "ext") else None,
            #             created_at=now if hasattr(Project, "created_at") else None,
            #             updated_at=now if hasattr(Project, "updated_at") else None,
            #         )
            #     else:
            #         proj.name = obj.name
            #         proj.start_date = obj.start_date
            #         proj.end_date = obj.end_date
            #         if hasattr(proj, "updated_at"):
            #             proj.updated_at = now
            #         if hasattr(proj, "ext") and proj.ext is None:
            #             proj.ext = {}
            #         proj.save(using=alias)
            # except Exception:
            #     # Project 모델/필드가 없거나 비활성화된 경우를 무시
            #     pass

    except IntegrityError:
        # 주로 code 중복(UNIQUE) 등
        # form.add_error("code", f"이미 사용 중인 계약번호입니다: {obj.code or '—'}")
        # errors_json = form.errors.get_json_data()
        # flat_errors = [e["message"] for _, errs in errors_json.items() for e in errs]
        form.add_error("code", f"이미 사용 중인 계약번호입니다: {obj.code or '—'}")
        errors_json = form.errors.get_json_data()
        flat_errors = [e["message"] for _, errs in errors_json.items() for e in errs]
        return render(
            request,
            "geoflow_ops/contracts/contract_detail.html",
            {
                "obj": None,
                "form": form,
                "edit_mode": True,
                "force_create": True,
                "errors": flat_errors,
                "client_selected": request.POST.get("client"),
                "subclient_selected": request.POST.get("sub_client"),
            },
        )

    messages.success(request, "계약을 생성했습니다.")
    return redirect("tenant:contract_detail", pk=obj.id)


def contract_form(request, pk=None):
    """Legacy compatibility form; Contract lifecycle/status input is ignored."""
    alias = _alias(request)
    inst = None
    if pk:
        inst = get_object_or_404(Contract.objects.using(alias), pk=pk)

    if request.method == "POST":
        # 폼 없이 request.POST 직접 바인딩(레거시 경로). Contract.status는
        # 더 이상 사용자 입력으로 받거나 저장하지 않습니다.
        code = request.POST.get("code") or None
        name = request.POST.get("name")
        start_date = request.POST.get("start_date")
        end_date = request.POST.get("end_date")
        amount = request.POST.get("amount") or None
        division = request.POST.get("division") or None

        client_id = request.POST.get("client_id") or None
        sub_client_id = request.POST.get("sub_client_id") or None

        with transaction.atomic(using=alias):
            if inst is None:
                inst = Contract()
            inst.name = name
            inst.start_date = start_date
            inst.end_date = end_date
            inst.amount = amount
            inst.division = division

            inst.client_id = client_id   # UUID 문자열이면 Django가 변환
            inst.sub_client_id = sub_client_id

            if not code:
                code = next_contract_code(alias)
            inst.code = code

            inst.save(using=alias)

            # 프로젝트 동기화 (없으면 생성, 있으면 이름/기간 맞춤)
            proj = Project.objects.using(alias).filter(contract=inst).first()
            # if not proj:
            #     Project.objects.using(alias).create(
            #         contract=inst,
            #         code=f"C{inst.code.replace('-', '')}",
            #         name=inst.name,
            #         start_date=inst.start_date,
            #         end_date=inst.end_date,
            #         status="active",
            #     )
            # else:
            #     # 필요 시 동기화
            #     proj.name = inst.name
            #     proj.start_date = inst.start_date
            #     proj.end_date = inst.end_date
            #     proj.save(using=alias)

        return redirect("contracts_list")  # 적절한 라우트

    return render(request, "geoflow_ops/contracts/detail.html", {
        "instance": inst
    })


def contract_delete(request, pk):
    alias = _alias(request)
    inst = get_object_or_404(Contract.objects.using(alias), pk=pk)
    if request.method == "POST":
        with transaction.atomic(using=alias):
            # FK CASCADE가 DB에 없다면, 수동 삭제:
            Project.objects.using(alias).filter(contract=inst).delete()
            inst.delete(using=alias)
        return redirect("contracts_list")
    return render(request, "geoflow_ops/contracts/confirm_delete.html", {"instance": inst})

# ----------------------------------------------------------------------------------------------------
# 파트너 리스트/상세
# ----------------------------------------------------------------------------------------------------
class PartnerListView(ListView):
    model = Partner
    template_name = "geoflow_ops/contracts/partner_list.html"
    context_object_name = "partners"
    paginate_by = None

    def get_queryset(self):
        return Partner.objects.using(_alias(self.request)).all().order_by("name")

@gf_perm_required("partners.view")
def partner_list(request):
    return PartnerListView.as_view()(request)

@login_required
@gf_perm_required("partners.view")
def partner_detail_page(request, pk):
    alias = _alias(request)
    obj = get_object_or_404(Partner.objects.using(alias), pk=pk)

    if request.method == "POST":
        form = PartnerForm(request.POST, instance=obj)
        if form.is_valid():
            inst = form.save(commit=False)
            inst.save(using=alias)
            messages.success(request, "저장했습니다.")
            return redirect("tenant:partner_detail", pk=obj.pk)  # ← 네임스페이스 정정
        # 유효성 실패 → 편집모드로 재렌더
        return render(
            request, "geoflow_ops/contracts/partner_detail.html",
            {
                "obj": obj,
                "form": form,
                "edit_mode": True,
                "errors": [e["message"] for _, errs in form.errors.get_json_data().items() for e in errs],
            }
        )

    # GET
    edit_mode = str(request.GET.get("edit", "")).lower() in ("1", "true", "yes")
    ctx = {"obj": obj, "edit_mode": edit_mode}
    if edit_mode:
        ctx["form"] = PartnerForm(instance=obj)
    return render(request, "geoflow_ops/contracts/partner_detail.html", ctx)

def partner_detail_json(request, pk):
    alias = _alias(request)
    obj = get_object_or_404(Partner.objects.using(alias), pk=pk)
    return JsonResponse({
        "id": obj.id,
        "partner_name": obj.name,
        "biz_no": getattr(obj, "biz_no", None),
        "rep_name": getattr(obj, "rep_name", None),
        "address": getattr(obj, "address", None),
        "partner_type": getattr(obj, "type", None),
        "status": getattr(obj, "status", None),
        "description": getattr(obj, "description", None),
        "phone": getattr(obj, "phone", None),
        "email": getattr(obj, "email", None),
    })

@login_required
@gf_perm_required("partners.create")
@require_http_methods(["GET", "POST"])
def partner_create(request):
    alias = _alias(request)

    if request.method == "GET":
        form = PartnerForm()
        return render(
            request, "geoflow_ops/contracts/partner_detail.html",
            {"obj": None, "form": form, "edit_mode": True, "force_create": True, "errors": []}
        )

    form = PartnerForm(request.POST)
    if not form.is_valid():
        flat_errors = [e["message"] for _, errs in form.errors.get_json_data().items() for e in errs]
        return render(
            request, "geoflow_ops/contracts/partner_detail.html",
            {"obj": None, "form": form, "edit_mode": True, "force_create": True, "errors": flat_errors}
        )

    obj = form.save(commit=False)

    # ✅ created_at / updated_at 채워주기 (DB가 NOT NULL이면 필수)
    now = timezone.now()
    if not getattr(obj, "created_at", None):
        obj.created_at = now
    obj.updated_at = now

    obj.save(using=alias)
    messages.success(request, "파트너를 생성했습니다.")
    return redirect("tenant:partner_detail", pk=obj.id)

@require_GET
@gf_perm_required("partners.view")
def partners_options(request):
    """Select2 등에서 파트너 자동완성/옵션 로딩용 API.
    - 같은 alias DB에서 Partner를 조회
    - q가 있으면 name/type LIKE 검색
    - limit으로 갯수 제한
    """
    alias = _alias(request)
    q = (request.GET.get("q") or "").strip()
    limit = int(request.GET.get("limit") or 50)

    qs = Partner.objects.using(alias).all()
    if q:
        qs = qs.filter(Q(name__icontains=q) | Q(type__icontains=q))
    qs = qs.order_by("name")[:limit]

    return JsonResponse({
        "results": [{"id": p.id, "text": f"{p.name} ({p.type or ''})"} for p in qs]
    })  # 텍스트 라벨은 UI에서 그대로 쓰면 됩니다.  :contentReference[oaicite:9]{index=9}
