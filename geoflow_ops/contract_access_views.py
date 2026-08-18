from __future__ import annotations

from django.contrib.auth.decorators import login_required
from django.http import HttpResponseBadRequest, HttpResponseForbidden
from django.shortcuts import redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_POST

from control.gf_authz.permissions import gf_has_perm

from .models import Attachment, Contract, Project
from .services.contract_document_access import (
    access_state,
    decide_request,
    pending_requests,
    request_access,
)
from .services.entity_access import authorize_scope_read, require_tenant_context


@never_cache
@login_required
@require_GET
def project_contract_document_panel(request, pk):
    alias = require_tenant_context(request)
    if not authorize_scope_read(request, alias, "project", pk):
        return HttpResponseForbidden("Forbidden")
    project = Project.objects.using(alias).filter(pk=pk).only("id", "contract_id").first()
    if not project or not project.contract_id:
        return HttpResponseBadRequest("Project contract not found")

    state = access_state(request, alias, project.contract_id)
    attachments = []
    if state.allowed:
        attachments = list(
            Attachment.objects.using(alias)
            .filter(
                entity_type="contract",
                entity_id=project.contract_id,
                active=True,
                deleted_at__isnull=True,
                is_deleted=False,
            )
            .order_by("purpose", "ord", "-created_at")
        )
    return render(
        request,
        "geoflow_ops/contracts/_project_contract_documents.html",
        {
            "project": project,
            "access_state": state,
            "contract_attachments": attachments,
        },
    )


@login_required
@require_POST
def project_contract_document_request(request, pk):
    alias = require_tenant_context(request)
    reason = str(request.POST.get("reason") or "").strip()[:1000]
    try:
        request_access(request, alias, pk, reason)
    except PermissionError:
        return HttpResponseForbidden("Forbidden")
    except ValueError as exc:
        return HttpResponseBadRequest(str(exc))
    return redirect("tenant:project_detail", pk=pk)


@never_cache
@login_required
@require_GET
def contract_document_request_panel(request, pk):
    alias = require_tenant_context(request)
    if not gf_has_perm(request, "contracts.edit"):
        return HttpResponseForbidden("Forbidden")
    if not Contract.objects.using(alias).filter(pk=pk).exists():
        return HttpResponseBadRequest("Contract not found")
    return render(
        request,
        "geoflow_ops/contracts/_contract_document_requests.html",
        {"access_requests": pending_requests(alias, pk), "contract_id": pk},
    )


@login_required
@require_POST
def contract_document_request_decide(request, request_id):
    alias = require_tenant_context(request)
    decision = str(request.POST.get("decision") or "").strip().lower()
    contract_id = str(request.POST.get("contract_id") or "").strip()
    try:
        decide_request(request, alias, request_id, decision)
    except PermissionError:
        return HttpResponseForbidden("Forbidden")
    except ValueError as exc:
        return HttpResponseBadRequest(str(exc))
    if contract_id:
        return redirect("tenant:contract_detail", pk=contract_id)
    return redirect("tenant:contract_list")
