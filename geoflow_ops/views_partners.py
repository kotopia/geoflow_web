from __future__ import annotations

from django.contrib import messages
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_http_methods
from django.views.generic import ListView

from control.gf_authz.permissions import gf_has_perm
from control.middleware import current_db_alias

from .forms import PartnerForm
from .models import Attachment, Partner


def _alias(request):
    return current_db_alias()


class PartnerListView(ListView):
    model = Partner
    template_name = "geoflow_ops/contracts/partner_list.html"
    context_object_name = "partners"
    paginate_by = None

    def get_queryset(self):
        return Partner.objects.using(_alias(self.request)).all().order_by("name")


def partner_list(request):
    return PartnerListView.as_view()(request)


def _partner_attachments(alias: str, partner_id):
    return list(
        Attachment.objects.using(alias)
        .filter(
            entity_type="partner",
            entity_id=partner_id,
            purpose="doc",
            active=True,
            deleted_at__isnull=True,
            is_deleted=False,
        )
        .order_by("ord", "-created_at")
    )


def _partner_context(request, obj, *, edit_mode: bool, form=None, errors=None):
    alias = _alias(request)
    context = {
        "obj": obj,
        "edit_mode": edit_mode,
        "can_edit_partner": gf_has_perm(request, "partners.create"),
        "attachments": _partner_attachments(alias, obj.id) if obj else [],
    }
    if form is not None:
        context["form"] = form
    if errors is not None:
        context["errors"] = errors
    return context


def partner_detail_page(request, pk):
    alias = _alias(request)
    obj = get_object_or_404(Partner.objects.using(alias), pk=pk)

    if request.method == "POST":
        form = PartnerForm(request.POST, instance=obj)
        if form.is_valid():
            inst = form.save(commit=False)
            inst.updated_at = timezone.now()
            inst.save(using=alias)
            messages.success(request, "저장했습니다.")
            return redirect("tenant:partner_detail", pk=obj.pk)

        errors = [
            error["message"]
            for _, field_errors in form.errors.get_json_data().items()
            for error in field_errors
        ]
        return render(
            request,
            "geoflow_ops/contracts/partner_detail.html",
            _partner_context(
                request,
                obj,
                edit_mode=True,
                form=form,
                errors=errors,
            ),
        )

    edit_mode = str(request.GET.get("edit", "")).lower() in {"1", "true", "yes"}
    if edit_mode and not gf_has_perm(request, "partners.create"):
        edit_mode = False

    form = PartnerForm(instance=obj) if edit_mode else None
    return render(
        request,
        "geoflow_ops/contracts/partner_detail.html",
        _partner_context(request, obj, edit_mode=edit_mode, form=form),
    )


@require_GET
def partner_detail_json(request, pk):
    alias = _alias(request)
    obj = get_object_or_404(Partner.objects.using(alias), pk=pk)
    return JsonResponse(
        {
            "id": str(obj.id),
            "partner_name": obj.name,
            "biz_no": obj.biz_no,
            "rep_name": obj.rep_name,
            "address": obj.address,
            "partner_type": obj.type,
            "status": obj.status,
            "description": obj.description,
            "phone": obj.phone,
            "email": obj.email,
        }
    )


@require_http_methods(["GET", "POST"])
def partner_create(request):
    alias = _alias(request)

    if request.method == "GET":
        return render(
            request,
            "geoflow_ops/contracts/partner_detail.html",
            {
                "obj": None,
                "form": PartnerForm(),
                "edit_mode": True,
                "force_create": True,
                "errors": [],
                "can_edit_partner": True,
                "attachments": [],
            },
        )

    form = PartnerForm(request.POST)
    if not form.is_valid():
        errors = [
            error["message"]
            for _, field_errors in form.errors.get_json_data().items()
            for error in field_errors
        ]
        return render(
            request,
            "geoflow_ops/contracts/partner_detail.html",
            {
                "obj": None,
                "form": form,
                "edit_mode": True,
                "force_create": True,
                "errors": errors,
                "can_edit_partner": True,
                "attachments": [],
            },
        )

    obj = form.save(commit=False)
    now = timezone.now()
    if not obj.created_at:
        obj.created_at = now
    obj.updated_at = now
    obj.save(using=alias)
    messages.success(request, "파트너를 생성했습니다.")
    return redirect("tenant:partner_detail", pk=obj.id)


@require_GET
def partners_options(request):
    alias = _alias(request)
    q = (request.GET.get("q") or "").strip()
    try:
        limit = max(1, min(int(request.GET.get("limit") or 50), 500))
    except (TypeError, ValueError):
        limit = 50

    qs = Partner.objects.using(alias).all()
    if q:
        qs = qs.filter(Q(name__icontains=q) | Q(type__icontains=q))
    qs = qs.order_by("name")[:limit]
    return JsonResponse(
        {"results": [{"id": str(p.id), "text": f"{p.name} ({p.type or ''})"} for p in qs]}
    )
