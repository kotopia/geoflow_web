from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import DatabaseError, connections
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_GET

from control.gf_authz.permissions import gf_has_perm
from geoflow_ops.models import Project
from geoflow_ops.services.entity_access import require_tenant_context

from .registry import domain_counts, feature_rows


def _require_gis_view(request):
    alias = require_tenant_context(request)
    if not gf_has_perm(request, "maps.view"):
        raise PermissionDenied("Permission denied")
    return alias


def _project_queryset(alias):
    return Project.objects.using(alias).order_by("-start_date", "name")


def _physical_feature_rows(alias, *, project_id=None):
    """Attach physical-table status/counts without making GIS rollout mandatory.

    Table names come only from the reviewed code registry. A tenant that has not
    received the GIS schema yet remains readable: its rows are returned with
    physical_status='NOT_APPLIED' rather than raising a database error.
    """
    rows = feature_rows()
    connection = connections[alias]
    schema_name = connection.ops.quote_name("gis")

    try:
        with connection.cursor() as cursor:
            for row in rows:
                table_name = row["physical_name"]
                cursor.execute("SELECT to_regclass(%s)", [f"gis.{table_name}"])
                exists = cursor.fetchone()[0] is not None
                row["physical_status"] = "READY" if exists else "NOT_APPLIED"
                row["row_count"] = None
                if not exists:
                    continue

                quoted_table = connection.ops.quote_name(table_name)
                sql = f"SELECT count(*) FROM {schema_name}.{quoted_table}"
                params = []
                if project_id is not None:
                    sql += " WHERE project_id = %s"
                    params.append(project_id)
                cursor.execute(sql, params)
                row["row_count"] = cursor.fetchone()[0]
    except DatabaseError:
        # Keep the registry page available during staged tenant rollout.
        for row in rows:
            row.setdefault("physical_status", "NOT_APPLIED")
            row.setdefault("row_count", None)

    return rows


@login_required
@require_GET
def dashboard(request):
    alias = _require_gis_view(request)
    projects = list(_project_queryset(alias)[:200])
    rows = _physical_feature_rows(alias)
    return render(
        request,
        "geoflow_ops/gis/dashboard.html",
        {
            "projects": projects,
            "features": rows,
            "domain_counts": domain_counts(),
            "feature_count": len(rows),
            "physical_ready_count": sum(1 for row in rows if row["physical_status"] == "READY"),
            "physical_object_count": sum((row["row_count"] or 0) for row in rows),
        },
    )


@login_required
@require_GET
def project_dashboard(request, project_id):
    alias = _require_gis_view(request)
    project = get_object_or_404(_project_queryset(alias), id=project_id)
    rows = _physical_feature_rows(alias, project_id=project.id)
    return render(
        request,
        "geoflow_ops/gis/project_dashboard.html",
        {
            "project": project,
            "features": rows,
            "domain_counts": domain_counts(),
            "feature_count": len(rows),
            "physical_ready_count": sum(1 for row in rows if row["physical_status"] == "READY"),
            "physical_object_count": sum((row["row_count"] or 0) for row in rows),
        },
    )


@login_required
@require_GET
def layer_registry_api(request):
    alias = _require_gis_view(request)
    return JsonResponse({"features": _physical_feature_rows(alias)})
