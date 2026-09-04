import json

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import DatabaseError, connections
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_GET

from control.gf_authz.permissions import gf_has_perm
from geoflow_ops.models import Project
from geoflow_ops.services.entity_access import require_tenant_context
from geoflow_ops.services.project_access import project_access_policy

from .layer_plan import (
    allowed_standard_names,
    gis_enabled_project_ids,
    project_layer_plan,
)
from .registry import FEATURE_TYPES, domain_counts, feature_rows


_GEOJSON_PROPERTY_CANDIDATES = (
    "id",
    "ftr_cde",
    "ftr_idn",
    "source_key",
    "description",
    "name",
    "code",
    "survey_code",
    "survey_date",
    "source_type",
    "etctxt",
)


def _require_gis_view(request):
    alias = require_tenant_context(request)
    if not gf_has_perm(request, "maps.view"):
        raise PermissionDenied("Permission denied")
    return alias


def _project_queryset(alias):
    return Project.objects.using(alias).order_by("-start_date", "name")


def _require_project_gis_access(request, alias, project_id):
    project = get_object_or_404(_project_queryset(alias), id=project_id)
    policy = project_access_policy(request, alias)
    if not policy.can_webgis_read(project.id):
        raise PermissionDenied("Permission denied")
    plan = project_layer_plan(alias, project.id)
    if plan.get("ready") and not plan.get("gis_enabled"):
        raise Http404("GIS is not enabled by this project's business scope.")
    return project, plan


def _registry_feature(value):
    key = (value or "").strip().lower()
    if not key:
        return None
    for item in FEATURE_TYPES:
        if key in (item.standard_name.lower(), item.physical_name.lower()):
            return item
    return None


def _parse_bbox(value):
    if not value:
        return None
    try:
        parts = [float(part.strip()) for part in value.split(",")]
    except (TypeError, ValueError):
        raise ValueError("bbox must be minx,miny,maxx,maxy")
    if len(parts) != 4:
        raise ValueError("bbox must contain four numbers")
    minx, miny, maxx, maxy = parts
    if not (-180 <= minx < maxx <= 180 and -90 <= miny < maxy <= 90):
        raise ValueError("bbox is outside EPSG:4326 bounds or has invalid extent")
    return minx, miny, maxx, maxy


def _parse_limit(value):
    if value in (None, ""):
        return 2000
    try:
        limit = int(value)
    except (TypeError, ValueError):
        raise ValueError("limit must be an integer")
    if limit < 1:
        raise ValueError("limit must be at least 1")
    return min(limit, 5000)


def _physical_feature_rows(alias, *, project_id=None, allowed_names=None):
    rows = feature_rows()
    if allowed_names is not None:
        allowed = {str(name).upper() for name in allowed_names}
        rows = [row for row in rows if row["standard_name"].upper() in allowed]

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
        for row in rows:
            row.setdefault("physical_status", "NOT_APPLIED")
            row.setdefault("row_count", None)
    return rows


def _geojson_property_columns(cursor, table_name):
    cursor.execute(
        """
        SELECT column_name
          FROM information_schema.columns
         WHERE table_schema='gis' AND table_name=%s
        """,
        [table_name],
    )
    actual = {row[0] for row in cursor.fetchall()}
    return [name for name in _GEOJSON_PROPERTY_CANDIDATES if name in actual]


@login_required
@require_GET
def dashboard(request):
    alias = _require_gis_view(request)
    policy = project_access_policy(request, alias)
    queryset = _project_queryset(alias)
    visible_ids = policy.visible_project_ids()
    if visible_ids is not None:
        queryset = queryset.filter(pk__in=visible_ids)
    enabled_ids = gis_enabled_project_ids(alias)
    if enabled_ids is not None:
        queryset = queryset.filter(pk__in=enabled_ids)

    projects = list(queryset[:200])
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
            "scope_capability_active": enabled_ids is not None,
        },
    )


@login_required
@require_GET
def project_dashboard(request, project_id):
    alias = _require_gis_view(request)
    project, plan = _require_project_gis_access(request, alias, project_id)
    allowed = allowed_standard_names(plan) if plan.get("ready") else None
    rows = _physical_feature_rows(alias, project_id=project.id, allowed_names=allowed)
    map_layers = [
        {
            "standard_name": row["standard_name"],
            "physical_name": row["physical_name"],
            "label": row["label"],
            "domain": row["domain"],
            "domain_label": row["domain_label"],
            "geometry_kind": row["geometry_kind"],
            "row_count": row["row_count"] or 0,
        }
        for row in rows
        if row["physical_status"] == "READY" and (row["row_count"] or 0) > 0
    ]
    return render(
        request,
        "geoflow_ops/gis/project_dashboard.html",
        {
            "project": project,
            "features": rows,
            "map_layers": map_layers,
            "layer_plan": plan,
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


@login_required
@require_GET
def project_layer_plan_api(request, project_id):
    alias = _require_gis_view(request)
    project, plan = _require_project_gis_access(request, alias, project_id)
    return JsonResponse(
        {
            "project": {
                "id": str(project.id),
                "code": project.code or "",
                "name": project.name or "",
                "status": project.status or "",
            },
            **plan,
        },
        json_dumps_params={"ensure_ascii": False},
    )


@login_required
@require_GET
def project_layer_geojson_api(request, project_id):
    alias = _require_gis_view(request)
    project, plan = _require_project_gis_access(request, alias, project_id)
    feature_type = _registry_feature(request.GET.get("layer"))
    if feature_type is None:
        return JsonResponse({"error": "Unknown or missing GIS layer."}, status=400)

    if plan.get("ready") and feature_type.standard_name.upper() not in allowed_standard_names(plan):
        raise Http404("GIS layer is not enabled by this project's business scope/profile.")

    try:
        bbox = _parse_bbox(request.GET.get("bbox"))
        limit = _parse_limit(request.GET.get("limit"))
    except ValueError as exc:
        return JsonResponse({"error": str(exc)}, status=400)

    connection = connections[alias]
    schema_name = connection.ops.quote_name("gis")
    table_name = connection.ops.quote_name(feature_type.physical_name)

    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT to_regclass(%s)", [f"gis.{feature_type.physical_name}"])
            if cursor.fetchone()[0] is None:
                return JsonResponse({"error": "GIS physical layer is not applied."}, status=404)

            property_columns = _geojson_property_columns(cursor, feature_type.physical_name)
            select_parts = ["ST_AsGeoJSON(geom, 8) AS geometry_json"]
            for column in property_columns:
                quoted = connection.ops.quote_name(column)
                if column == "id":
                    select_parts.append(f"{quoted}::text AS {quoted}")
                else:
                    select_parts.append(quoted)

            sql = (
                f"SELECT {', '.join(select_parts)} "
                f"FROM {schema_name}.{table_name} "
                "WHERE project_id=%s AND geom IS NOT NULL"
            )
            params = [project.id]
            if bbox is not None:
                sql += " AND ST_Intersects(geom, ST_MakeEnvelope(%s,%s,%s,%s,4326))"
                params.extend(bbox)
            sql += " ORDER BY id LIMIT %s"
            params.append(limit + 1)

            cursor.execute(sql, params)
            columns = [item[0] for item in cursor.description]
            records = [dict(zip(columns, row)) for row in cursor.fetchall()]
    except DatabaseError:
        return JsonResponse({"error": "GIS layer query failed."}, status=503)

    truncated = len(records) > limit
    records = records[:limit]
    features = []
    for record in records:
        geometry_json = record.pop("geometry_json", None)
        if not geometry_json:
            continue
        features.append(
            {
                "type": "Feature",
                "id": record.get("id"),
                "geometry": json.loads(geometry_json),
                "properties": {
                    **record,
                    "layer": feature_type.standard_name,
                    "layer_label": feature_type.label,
                    "domain": feature_type.domain,
                },
            }
        )

    return JsonResponse(
        {
            "type": "FeatureCollection",
            "features": features,
            "meta": {
                "project_id": str(project.id),
                "layer": feature_type.standard_name,
                "physical_name": feature_type.physical_name,
                "geometry_kind": feature_type.geometry_kind,
                "bbox": bbox,
                "limit": limit,
                "truncated": truncated,
                "returned": len(features),
            },
        },
        json_dumps_params={"ensure_ascii": False},
    )
