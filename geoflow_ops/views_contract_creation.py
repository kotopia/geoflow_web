from __future__ import annotations

import logging

from django.contrib import messages
from django.db import IntegrityError
from django.shortcuts import redirect, render
from django.utils import timezone

from control.middleware import current_db_alias

from .forms import ContractForm
from .models import MyOrgUnit, Partner
from .services.contract_project_creation import save_new_contract_with_project
from .utils.ctr_utils import next_contract_code


logger = logging.getLogger(__name__)


def _bind_tenant_choices(form, alias: str) -> None:
    if "client" in form.fields:
        form.fields["client"].queryset = Partner.objects.using(alias).all()
    if "sub_client" in form.fields:
        form.fields["sub_client"].queryset = Partner.objects.using(alias).all()
    if "org_unit" in form.fields:
        form.fields["org_unit"].queryset = MyOrgUnit.objects.using(alias).all()


def _render_create_form(request, form, *, errors=None):
    return render(
        request,
        "geoflow_ops/contracts/contract_detail.html",
        {
            "obj": None,
            "form": form,
            "edit_mode": True,
            "force_create": True,
            "errors": list(errors or []),
            "client_selected": request.POST.get("client") if request.method == "POST" else None,
            "subclient_selected": request.POST.get("sub_client") if request.method == "POST" else None,
        },
    )


def contract_create(request):
    """Active /contracts/new/ implementation: contract and project succeed or roll back together."""
    alias = current_db_alias()
    if not alias:
        raise RuntimeError("tenant database alias is required")

    if request.method == "GET":
        form = ContractForm(initial={"code": next_contract_code(alias)})
        _bind_tenant_choices(form, alias)
        return _render_create_form(request, form)

    form = ContractForm(request.POST)
    _bind_tenant_choices(form, alias)
    if not form.is_valid():
        errors_json = form.errors.get_json_data()
        flat_errors = [item["message"] for _, items in errors_json.items() for item in items]
        return _render_create_form(request, form, errors=flat_errors)

    contract = form.save(commit=False)
    now = timezone.now()
    try:
        save_new_contract_with_project(alias, contract, now=now)
    except IntegrityError:
        logger.exception("atomic contract/project creation failed with integrity error")
        form.add_error(None, "계약과 프로젝트를 함께 생성하지 못했습니다. 입력값을 확인해 주세요.")
        errors_json = form.errors.get_json_data()
        flat_errors = [item["message"] for _, items in errors_json.items() for item in items]
        return _render_create_form(request, form, errors=flat_errors)

    messages.success(request, "계약과 프로젝트를 생성했습니다.")
    return redirect("tenant:contract_detail", pk=contract.id)
