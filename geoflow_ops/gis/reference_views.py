from __future__ import annotations

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.db import connections
from django.views.decorators.http import require_GET

from geoflow_ops.services.entity_access import require_tenant_context

from .layer_plan import allowed_standard_names
from .qfield_auth import qfield_ticket_required
from .qfield_ticket_roaming_views import _ticket_project_and_plan
from .qgis_views import _require_project, _require_qgis_context
from .reference_catalog import project_reference_catalog
from .workers import project_workers


def _catalog_response(alias: str, plan: dict, request=None, project_id=None) -> JsonResponse:
    payload = project_reference_catalog(
        using=alias,
        standard_names=allowed_standard_names(plan),
    )
    # The Final Layer Plan already resolves this project's selected catalog IDs.
    # Expose their central active L2 labels; never infer scope from Survey data.
    ids = [r['catalog_item_id'] for r in plan.get('capabilities', [])
           if r.get('catalog_level') == 2]
    with connections['default'].cursor() as cursor:
        cursor.execute('''SELECT id::text,name FROM catalog.category_node
                          WHERE level=2 AND active AND id=ANY(%s::uuid[]) ORDER BY name,id''', [ids])
        payload['business_types'] = [{'code': row[0], 'label': row[1]} for row in cursor.fetchall()]
    if request is not None:
        payload["current_user"], payload["workers"] = project_workers(request, alias, project_id, plan)
    response = JsonResponse(payload, json_dumps_params={"ensure_ascii": False})
    response["Cache-Control"] = "private, no-store"
    return response


@login_required
@require_GET
def qgis_reference_catalog_api(request, project_id):
    """Serve project-scoped GIS reference values to WebGIS/QGIS clients."""

    alias = _require_qgis_context(request)
    _project, _policy, plan = _require_project(request, alias, project_id)
    return _catalog_response(alias, plan, request, project_id)


@qfield_ticket_required(write=False)
@require_GET
def qfield_reference_catalog_api(request, project_id):
    """Serve the same GIS-owned catalog through a signed QField ticket."""

    alias = require_tenant_context(request)
    project, plan, error = _ticket_project_and_plan(request, alias, project_id)
    if error is not None:
        return error
    if project is None or plan is None:
        return JsonResponse({"ok": False, "error": "qfield_reference_scope_invalid"}, status=403)
    return _catalog_response(alias, plan)
