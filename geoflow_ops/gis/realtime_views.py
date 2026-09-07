from __future__ import annotations

import json
import uuid

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import DatabaseError, connections
from django.http import Http404, JsonResponse
from django.views.decorators.http import require_GET

from control.gf_authz.permissions import gf_has_perm
from geoflow_ops.models import Project
from geoflow_ops.services.entity_access import require_tenant_context
from geoflow_ops.services.project_access import project_access_policy

from .layer_plan import allowed_standard_names, project_layer_plan
from .views import _geojson_property_columns, _parse_bbox, _registry_feature


MAX_FEATURE_IDS = 200


def _parse_feature_ids(value: str | None) -> tuple[str, ...]:
    if not value:
        return ()
    values = [item.strip() for item in str(value).split(",") if item.strip()]
    if len(values) > MAX_FEATURE_IDS:
        raise ValueError(f"ids accepts at most {MAX_FEATURE_IDS} UUIDs")

    result = []
    seen = set()
    for raw in values:
        try:
            normalized = str(uuid.UUID(raw))
        except (ValueError, TypeError, AttributeError) as exc:
            raise ValueError("ids must contain valid UUIDs") from exc
        if normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
    return tuple(result)


def _require_project(request, alias, project_id):
    project = Project.objects.using(alias).filter(id=project_id).first()
    if project is None:
        raise Http404("Project not found")
    policy = project_access_policy(request, alias)
    if not policy.can_webgis_read(project.id):
        raise PermissionDenied("Permission denied")
    plan = project_layer_plan(alias, project.id)
    if plan.get("ready") and not plan.get("gis_enabled"):
        raise Http404("GIS is not enabled by this project's business scope.")
    return project, plan


@login_required
@require_GET
def project_feature_batch_api(request, project_id):
    alias = require_tenant_context(request)
    if not gf_has_perm(request, "maps.view"):
        raise PermissionDenied("Permission denied")

    project, plan = _require_project(request, alias, project_id)
    feature_type = _registry_feature(request.GET.get("layer"))
    if feature_type is None:
        return JsonResponse({"error": "Unknown or missing GIS layer."}, status=400)
    if plan.get("ready") and feature_type.standard_name.upper() not in allowed_standard_names(plan):
        raise Http404("GIS layer is not enabled by this project's business scope/profile.")

    try:
        object_ids = _parse_feature_ids(request.GET.get("ids"))
        bbox = _parse_bbox(request.GET.get("bbox"))
    except ValueError as exc:
        return JsonResponse({"error": str(exc)}, status=400)
    if not object_ids:
        return JsonResponse(
            {
                "type": "FeatureCollection",
                "features": [],
                "meta": {"project_id": str(project.id), "layer": feature_type.standard_name},
            }
        )

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
                "WHERE project_id=%s AND id = ANY(%s::uuid[]) AND geom IS NOT NULL"
            )
            params = [project.id, list(object_ids)]
            if bbox is not None:
                sql += " AND ST_Intersects(geom, ST_MakeEnvelope(%s,%s,%s,%s,4326))"
                params.extend(bbox)
            sql += " ORDER BY id"
            cursor.execute(sql, params)
            columns = [item[0] for item in cursor.description]
            records = [dict(zip(columns, row)) for row in cursor.fetchall()]
    except DatabaseError:
        return JsonResponse({"error": "GIS feature refresh query failed."}, status=503)

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
                "requested": len(object_ids),
                "returned": len(features),
                "bbox": bbox,
            },
        },
        json_dumps_params={"ensure_ascii": False},
    )
