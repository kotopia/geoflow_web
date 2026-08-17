from __future__ import annotations

from uuid import UUID

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.views.decorators.http import require_GET, require_POST, require_http_methods

from control.gf_authz.permissions import gf_has_perm

from . import (
    views_catalog,
    views_contracts,
    views_execution,
    views_myinfo,
    views_project_members,
    views_projects,
)
from .models import Contract
from .services.contract_project_pair import (
    contract_id_from_create_response,
    create_project_for_new_contract,
)
from .services.entity_access import (
    authorize_scope_read,
    authorize_scope_write,
    require_tenant_context,
)


def _require(request, code: str) -> None:
    require_tenant_context(request)
    if not gf_has_perm(request, code):
        raise PermissionDenied("Permission denied")


def _require_project(request, pk, *, write: bool) -> str:
    alias = require_tenant_context(request)
    allowed = (
        authorize_scope_write(request, alias, "project", pk)
        if write
        else authorize_scope_read(request, alias, "project", pk)
    )
    if not allowed:
        raise PermissionDenied("Permission denied")

    # Exact-project bridge for older internal views that still carry a generic
    # projects.view/edit decorator. It is request-local and never broadens to a
    # different project or a tenant-wide permission.
    request._gf_project_scope_authorized = {
        "project_id": str(pk),
        "read": True,
        "write": bool(write),
    }
    return alias


@login_required
@require_GET
def contract_list(request):
    _require(request, "contracts.view")
    return views_contracts.contract_list(request)


@login_required
@require_http_methods(["GET", "POST"])
def contract_create(request):
    _require(request, "contracts.create")
    if request.method != "POST":
        return views_contracts.contract_create(request)

    alias = require_tenant_context(request)
    with transaction.atomic(using=alias):
        response = views_contracts.contract_create(request)
        if not (300 <= int(getattr(response, "status_code", 0)) < 400):
            return response

        contract_id = contract_id_from_create_response(response)
        contract = Contract.objects.using(alias).get(pk=contract_id)
        create_project_for_new_contract(alias, contract)
        return response


@login_required
@require_http_methods(["GET", "POST"])
def contract_detail(request, pk):
    _require(request, "contracts.view")
    if request.method == "POST" and not gf_has_perm(request, "contracts.edit"):
        raise PermissionDenied("Permission denied")
    return views_contracts.contract_detail_page(request, pk)


@login_required
@require_GET
def contract_json(request, pk):
    _require(request, "contracts.view")
    return views_contracts.contract_json(request, pk)


@login_required
@require_GET
def partner_list(request):
    _require(request, "partners.view")
    return views_contracts.partner_list(request)


@login_required
@require_http_methods(["GET", "POST"])
def partner_create(request):
    _require(request, "partners.create")
    return views_contracts.partner_create(request)


@login_required
@require_http_methods(["GET", "POST"])
def partner_detail(request, pk):
    _require(request, "partners.view")
    if request.method == "POST" and not gf_has_perm(request, "partners.create"):
        raise PermissionDenied("Permission denied")
    return views_contracts.partner_detail_page(request, pk)


@login_required
@require_GET
def partner_json(request, pk):
    _require(request, "partners.view")
    return views_contracts.partner_detail_json(request, pk)


@login_required
@require_GET
def partner_options(request):
    _require(request, "partners.view")
    return views_contracts.partners_options(request)


@login_required
@require_GET
def project_list(request):
    _require(request, "projects.view")
    return views_projects.ProjectListView.as_view()(request)


@login_required
@require_http_methods(["GET", "POST"])
def project_detail(request, pk):
    _require_project(request, pk, write=request.method == "POST")
    return views_projects.project_detail_page(request, pk)


@login_required
@require_GET
def project_json(request, pk):
    _require_project(request, pk, write=False)
    return views_projects.project_json(request, pk)


@login_required
@require_GET
def project_members_panel(request, pk):
    _require_project(request, pk, write=False)
    return views_project_members.project_members_panel(request, pk)


@login_required
@require_GET
def project_summary(request, pk):
    _require_project(request, pk, write=True)
    return views_execution.project_task_modal(request, pk)


@login_required
@require_POST
def project_summary_save(request, pk):
    _require_project(request, pk, write=True)
    return views_execution.project_task_save(request, pk)


@login_required
@require_GET
def catalog_board(request):
    _require(request, "projects.view")
    project_id = request.GET.get("project_id")
    if project_id:
        try:
            project_uuid = UUID(str(project_id))
        except (TypeError, ValueError, AttributeError):
            raise PermissionDenied("Permission denied")
        _require_project(request, project_uuid, write=False)
    return views_catalog.catalog_board(request)


@login_required
@require_GET
def project_scope_modal(request, pk):
    _require_project(request, pk, write=True)
    return views_catalog.project_scope_modal(request, pk)


@login_required
@require_GET
def project_scope_data(request, pk):
    _require_project(request, pk, write=True)
    return views_catalog.project_scope_data(request, pk)


@login_required
@require_POST
def project_scope_save(request, pk):
    _require_project(request, pk, write=True)
    return views_catalog.project_scope_save(request, pk)


@login_required
@require_GET
def project_scope_summary(request, pk):
    _require_project(request, pk, write=False)
    return views_catalog.project_scope_summary(request, pk)


@login_required
@require_POST
def project_member_save(request, pk):
    _require_project(request, pk, write=True)
    return views_project_members.project_member_save(request, pk)


@login_required
@require_POST
def project_member_revoke(request, pk, member_id):
    _require_project(request, pk, write=True)
    return views_project_members.project_member_revoke(request, pk, member_id)


@login_required
@require_GET
def my_projects_api(request):
    _require(request, "projects.view")
    return views_project_members.my_projects_api(request)


@login_required
@require_GET
def project_access_api(request, pk):
    _require_project(request, pk, write=False)
    return views_project_members.project_access_api(request, pk)


@login_required
@require_GET
def orgunit_list(request):
    _require(request, "directory.view")
    return views_myinfo.orgunit_list(request)


@login_required
@require_GET
def orgunit_detail(request, pk):
    _require(request, "directory.view")
    return views_myinfo.orgunit_detail(request, pk)


@login_required
@require_http_methods(["GET", "POST"])
def orgunit_create(request):
    _require(request, "directory.edit")
    return views_myinfo.orgunit_create(request)


@login_required
@require_http_methods(["GET", "POST"])
def orgunit_update(request, pk):
    _require(request, "directory.edit")
    return views_myinfo.orgunit_update(request, pk)


@login_required
@require_GET
def event_modal_ui(request):
    alias = require_tenant_context(request)
    scope_type = str(request.GET.get("scope_type") or "").strip().lower()
    try:
        scope_id = UUID(str(request.GET.get("scope_id") or ""))
    except (TypeError, ValueError, AttributeError):
        raise PermissionDenied("Permission denied")
    if not authorize_scope_read(request, alias, scope_type, scope_id):
        raise PermissionDenied("Permission denied")
    return views_contracts.event_modal_ui(request)
