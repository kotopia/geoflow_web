import json
from urllib.parse import quote, urlencode

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import DatabaseError, connections, transaction
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.views.decorators.http import require_GET, require_POST
from django.views.decorators.csrf import csrf_protect, ensure_csrf_cookie

from control.gf_authz.permissions import gf_has_perm
from geoflow_ops.models import Project
from geoflow_ops.services.entity_access import require_tenant_context
from geoflow_ops.services.project_access import project_access_policy

from .changeset import changeset_runtime_enabled, project_current_revision
from .events import realtime_runtime_enabled
from .layer_plan import (
    allowed_standard_names,
    allowed_standard_names_for_projects,
    gis_enabled_project_ids,
    project_layer_plan,
    require_enabled_layer_plan,
)
from .qfield_auth import (
    issue_qfield_package_import_token,
    qfield_ticket_runtime_enabled,
)
from .registry import domain_counts_for_rows, feature_by_name, feature_rows
from .spatial_reference_views import map_config


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


def _require_project_gis_access(request, alias, project_id, *, allow_unready=False, allow_disabled=False):
    project = get_object_or_404(_project_queryset(alias), id=project_id)
    policy = project_access_policy(request, alias)
    if not policy.can_webgis_read(project.id):
        raise PermissionDenied("Permission denied")
    plan = project_layer_plan(alias, project.id)
    if not allow_unready:
        require_enabled_layer_plan(plan)
    elif plan.get("ready") and not plan.get("gis_enabled") and not allow_disabled:
        raise Http404("GIS is not enabled by this project's business scope.")
    return project, plan


def _registry_feature(value):
    return feature_by_name(value)


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


def _physical_feature_rows(
    alias,
    *,
    project_id=None,
    project_ids=None,
    allowed_names=None,
):
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
                elif project_ids is not None:
                    scoped_ids = [str(value) for value in project_ids]
                    if not scoped_ids:
                        row["row_count"] = 0
                        continue
                    sql += " WHERE project_id = ANY(%s::uuid[])"
                    params.append(scoped_ids)
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


def _qfield_open_url(request, alias: str, project) -> str:
    if not qfield_ticket_runtime_enabled() or not changeset_runtime_enabled(alias):
        return ""
    group_id = request.session.get("group_id") or request.session.get("group_uuid")
    user = getattr(request, "user", None)
    email = str(
        getattr(user, "email", None)
        or getattr(user, "username", None)
        or ""
    ).strip().lower()
    user_id = getattr(user, "pk", None)
    if not group_id or not email or user_id is None:
        return ""
    token = issue_qfield_package_import_token(
        project_id=str(project.id),
        alias=alias,
        group_id=str(group_id),
        user_id=str(user_id),
        email=email,
        roles=request.session.get("gf_roles") or [],
        perms=request.session.get("gf_perms") or [],
    )
    import_path = reverse(
        "gis:qfield_package_import_api",
        kwargs={"project_id": project.id},
    )
    package_url = request.build_absolute_uri(
        f"{import_path}?{urlencode({'token': token})}"
    )
    return "qfield://local?import=" + quote(package_url, safe="")


@login_required
@require_GET
@ensure_csrf_cookie
def dashboard(request):
    alias = _require_gis_view(request)
    policy = project_access_policy(request, alias)
    queryset = _project_queryset(alias)
    visible_ids = policy.visible_project_ids()
    if visible_ids is not None:
        queryset = queryset.filter(pk__in=visible_ids)
    enabled_ids = gis_enabled_project_ids(alias)
    if enabled_ids is None:
        queryset = queryset.none()
    else:
        queryset = queryset.filter(pk__in=enabled_ids)

    projects = list(queryset)
    map_projects = []
    for project in projects:
        shape = _business_area(project.ext)
        project.gis_location_registered = shape is not None
        if shape is not None:
            map_projects.append({"type": "Feature", "geometry": shape, "properties": {
                "code": project.code or "번호 미등록", "name": project.name or "",
                "url": reverse("gis:project_dashboard", args=[project.id])}})
    project_ids = [project.id for project in projects]
    dashboard_layers = (
        allowed_standard_names_for_projects(alias, project_ids)
        if enabled_ids is not None
        else set()
    )
    rows = (
        _physical_feature_rows(
            alias,
            project_ids=project_ids,
            allowed_names=dashboard_layers,
        )
        if enabled_ids is not None
        else []
    )
    return render(
        request,
        "geoflow_ops/gis/dashboard.html",
        {
            "projects": projects,
            "map_projects": map_projects,
            "located_project_count": len(map_projects),
            "unlocated_project_count": len(projects) - len(map_projects),
            "vworld_map_config": map_config(),
            "features": rows,
            "domain_counts": domain_counts_for_rows(rows),
            "feature_count": len(rows),
            "physical_ready_count": sum(1 for row in rows if row["physical_status"] == "READY"),
            "physical_object_count": sum((row["row_count"] or 0) for row in rows),
            "scope_capability_active": enabled_ids is not None,
        },
    )


@login_required
@require_GET
@ensure_csrf_cookie
def project_dashboard(request, project_id):
    alias = _require_gis_view(request)
    project, plan = _require_project_gis_access(
        request, alias, project_id, allow_unready=True
    )
    allowed = allowed_standard_names(plan)
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
        if row["physical_status"] == "READY"
    ]
    try:
        webgis_delta_enabled = changeset_runtime_enabled(alias)
    except DatabaseError:
        webgis_delta_enabled = False
    webgis_revision = 0
    if webgis_delta_enabled:
        try:
            webgis_revision = project_current_revision(alias, str(project.id))
        except DatabaseError:
            # The map remains usable even if revision metadata is temporarily
            # unavailable. The browser Delta poll retries from revision zero.
            webgis_revision = 0
    return render(
        request,
        "geoflow_ops/gis/project_dashboard.html",
        {
            "project": project,
            "features": rows,
            "map_layers": map_layers,
            "vworld_map_config": map_config(project.id),
            "business_area": _business_area(project.ext),
            "can_edit_business_area": gf_has_perm(request, "projects.edit") and project_access_policy(request, alias).can_edit_project(project.id),
            "webgis_revision": webgis_revision,
            "webgis_delta_enabled": webgis_delta_enabled,
            "webgis_realtime_enabled": realtime_runtime_enabled(),
            "layer_plan": plan,
            "domain_counts": domain_counts_for_rows(rows),
            "feature_count": len(rows),
            "physical_ready_count": sum(1 for row in rows if row["physical_status"] == "READY"),
            "physical_object_count": sum((row["row_count"] or 0) for row in rows),
            "qfield_open_url": (
                _qfield_open_url(request, alias, project)
                if plan.get("ready") and plan.get("gis_enabled")
                else ""
            ),
        },
    )


@login_required
@require_GET
def layer_registry_api(request):
    alias = _require_gis_view(request)
    policy = project_access_policy(request, alias)
    queryset = _project_queryset(alias)
    visible_ids = policy.visible_project_ids()
    if visible_ids is not None:
        queryset = queryset.filter(pk__in=visible_ids)
    enabled_ids = gis_enabled_project_ids(alias)
    if enabled_ids is None:
        return JsonResponse(
            {"features": [], "error": "gis_foundation_unavailable"}, status=503
        )
    queryset = queryset.filter(pk__in=enabled_ids)
    project_ids = list(queryset.values_list("id", flat=True)[:5000])
    allowed = allowed_standard_names_for_projects(alias, project_ids)
    return JsonResponse(
        {
            "features": _physical_feature_rows(
                alias, project_ids=project_ids, allowed_names=allowed
            )
        }
    )


@login_required
@require_GET
def project_layer_plan_api(request, project_id):
    alias = _require_gis_view(request)
    project, plan = _require_project_gis_access(
        request, alias, project_id, allow_unready=True
    )
    status = 200 if plan.get("ready") else 503
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
        status=status,
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

    if feature_type.standard_name.upper() not in allowed_standard_names(plan):
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
            if feature_type.physical_name == "survey":
                sql += " AND deleted_at IS NULL"
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


def _business_area(extension):
    """Explicit project-owned geometry only; never infer from facility extents."""
    from django.contrib.gis.geos import GEOSGeometry
    from django.contrib.gis.geos.error import GEOSException
    import math
    value = extension.get("gis_business_area") if isinstance(extension, dict) else None
    if value is None:
        return None
    try:
        if not isinstance(value, dict) or value.get("type") not in {"Point", "Polygon", "MultiPolygon"}:
            return None
        shape = GEOSGeometry(json.dumps(value), srid=4326)
        if shape.empty or not shape.valid or shape.num_coords > 5000:
            return None
        bounds = shape.extent
        if not all(math.isfinite(v) for v in bounds) or not (
            -180 <= bounds[0] <= bounds[2] <= 180 and -85 <= bounds[1] <= bounds[3] <= 85
        ):
            return None
        return json.loads(shape.geojson)
    except (ValueError, TypeError, GEOSException):
        return None


@login_required
@require_POST
@csrf_protect
def project_business_area(request, project_id):
    alias = _require_gis_view(request)
    project, _plan = _require_project_gis_access(request, alias, project_id)
    if not gf_has_perm(request, "projects.edit") or not project_access_policy(request, alias).can_edit_project(project.id):
        raise PermissionDenied("Permission denied")
    try:
        if len(request.body) > 200000:
            raise ValueError
        payload = json.loads(request.body)
        if not isinstance(payload, dict) or "geometry" not in payload or "previous" not in payload:
            raise ValueError
        shape = _business_area({"gis_business_area": payload["geometry"]})
        if payload["geometry"] is not None and shape is None:
            raise ValueError
        with transaction.atomic(using=alias):
            current = Project.objects.using(alias).select_for_update().get(pk=project.id)
            if current.ext is not None and not isinstance(current.ext, dict):
                raise ValueError
            extension = dict(current.ext or {})
            if _business_area(extension) != payload["previous"]:
                return JsonResponse({"ok": False, "error": "사업지역이 변경되었습니다. 새로고침 후 다시 시도하세요."}, status=409)
            if shape is None:
                extension.pop("gis_business_area", None)
            else:
                extension["gis_business_area"] = shape
            from django.utils import timezone
            Project.objects.using(alias).filter(pk=project.id).update(ext=extension, updated_at=timezone.now())
        response = JsonResponse({"ok": True, "geometry": shape})
        response["Cache-Control"] = "no-store"
        return response
    except (ValueError, TypeError):
        return JsonResponse({"ok": False, "error": "EPSG:4326의 점 또는 사업지역 면 GeoJSON을 지정하세요."}, status=400)
