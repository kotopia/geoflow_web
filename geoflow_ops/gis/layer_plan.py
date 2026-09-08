from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from django.db import DatabaseError, connections
from django.http import Http404


DEFAULT_PROFILE_CODE = "GEOFLOW_DEV_BASE"
_REQUIRED_TABLES = (
    "prj.scope_item",
    "gis.capability",
    "gis.capability_feature",
    "gis.scope_binding",
    "gis.profile",
    "gis.profile_feature",
    "gis.project_profile",
    "gis.meta_feature_type",
)


def _table_exists(alias: str, relation: str) -> bool:
    try:
        with connections[alias].cursor() as cursor:
            cursor.execute("SELECT to_regclass(%s) IS NOT NULL", [relation])
            row = cursor.fetchone()
        return bool(row and row[0])
    except DatabaseError:
        return False


def scope_capability_ready(alias: str) -> bool:
    return all(_table_exists(alias, relation) for relation in _REQUIRED_TABLES)


def gis_enabled_project_ids(alias: str) -> set[str] | None:
    """Return projects whose scope/profile intersection has an active layer.

    None means the capability layer is not applied. Callers must fail closed and
    must not substitute the process-wide feature registry for project metadata.
    """
    if not scope_capability_ready(alias):
        return None
    with connections[alias].cursor() as cursor:
        cursor.execute(
            """
            WITH candidate_projects AS (
                SELECT DISTINCT s.project_id
                  FROM prj.scope_item s
                  JOIN gis.scope_binding b
                    ON b.active
                   AND (
                        (b.catalog_level=2 AND b.catalog_item_id=s.lv2_id) OR
                        (b.catalog_level=3 AND b.catalog_item_id=s.lv3_id) OR
                        (b.catalog_level=4 AND b.catalog_item_id=s.lv4_id)
                   )
                  JOIN gis.capability c ON c.id=b.capability_id AND c.active
            ), selected_profiles AS (
                SELECT cp.project_id,
                       COALESCE(
                           (
                               SELECT pp.profile_id
                                 FROM gis.project_profile pp
                                 JOIN gis.profile p ON p.id=pp.profile_id AND p.active
                                WHERE pp.project_id=cp.project_id AND pp.status='active'
                                LIMIT 1
                           ),
                           (
                               SELECT p.id
                                 FROM gis.profile p
                                WHERE p.code=%s AND p.active
                                LIMIT 1
                           )
                       ) AS profile_id
                  FROM candidate_projects cp
            )
            SELECT DISTINCT s.project_id::text
              FROM prj.scope_item s
              JOIN selected_profiles sp ON sp.project_id=s.project_id
              JOIN gis.scope_binding b
                ON b.active
               AND (
                    (b.catalog_level=2 AND b.catalog_item_id=s.lv2_id) OR
                    (b.catalog_level=3 AND b.catalog_item_id=s.lv3_id) OR
                    (b.catalog_level=4 AND b.catalog_item_id=s.lv4_id)
               )
              JOIN gis.capability c ON c.id=b.capability_id AND c.active
              JOIN gis.capability_feature cf
                ON cf.capability_id=c.id AND cf.enabled
              JOIN gis.profile_feature pf
                ON pf.profile_id=sp.profile_id
               AND pf.feature_type_id=cf.feature_type_id
               AND pf.enabled
              JOIN gis.meta_feature_type ft
                ON ft.id=cf.feature_type_id AND ft.active
            """
            ,
            [DEFAULT_PROFILE_CODE],
        )
        return {row[0] for row in cursor.fetchall()}


def _profile_row(alias: str, project_id) -> dict[str, Any] | None:
    with connections[alias].cursor() as cursor:
        cursor.execute(
            """
            SELECT p.id::text,p.code,p.name,pp.status,pp.auto_assigned,'project' AS source
              FROM gis.project_profile pp
              JOIN gis.profile p ON p.id=pp.profile_id AND p.active
             WHERE pp.project_id=%s AND pp.status='active'
             LIMIT 1
            """,
            [str(project_id)],
        )
        row = cursor.fetchone()
        if not row:
            cursor.execute(
                """
                SELECT p.id::text,p.code,p.name,'active',true,'fallback' AS source
                  FROM gis.profile p
                 WHERE p.code=%s AND p.active
                 LIMIT 1
                """,
                [DEFAULT_PROFILE_CODE],
            )
            row = cursor.fetchone()
    if not row:
        return None
    return {
        "id": row[0],
        "code": row[1],
        "name": row[2],
        "status": row[3],
        "auto_assigned": bool(row[4]),
        "source": row[5],
    }


def project_layer_plan(alias: str, project_id) -> dict[str, Any]:
    """Resolve one project's GIS capability/profile/layer plan from metadata.

    Business scope remains in prj.scope_item. GIS-specific meaning is supplied by
    gis.scope_binding/capability metadata. The final layer set is the intersection
    of capability_feature and profile_feature, so WebGIS/QGIS/QField can consume
    exactly the same result without separate hardcoded layer rules.
    """
    if not scope_capability_ready(alias):
        return {
            "ready": False,
            "gis_enabled": False,
            "project_id": str(project_id),
            "profile": None,
            "capabilities": [],
            "layers": [],
            "reason": "scope_capability_not_applied",
        }

    profile = _profile_row(alias, project_id)
    if profile is None:
        return {
            "ready": True,
            "gis_enabled": False,
            "project_id": str(project_id),
            "profile": None,
            "capabilities": [],
            "layers": [],
            "reason": "active_profile_not_found",
        }

    with connections[alias].cursor() as cursor:
        cursor.execute(
            """
            SELECT DISTINCT c.id::text,c.code,c.name,c.sort_order
              FROM prj.scope_item s
              JOIN gis.scope_binding b
                ON b.active
               AND (
                    (b.catalog_level=2 AND b.catalog_item_id=s.lv2_id) OR
                    (b.catalog_level=3 AND b.catalog_item_id=s.lv3_id) OR
                    (b.catalog_level=4 AND b.catalog_item_id=s.lv4_id)
               )
              JOIN gis.capability c ON c.id=b.capability_id AND c.active
             WHERE s.project_id=%s
             ORDER BY c.sort_order,c.code
            """,
            [str(project_id)],
        )
        capability_rows = cursor.fetchall()

        capabilities = [
            {"id": row[0], "code": row[1], "name": row[2], "sort_order": row[3]}
            for row in capability_rows
        ]
        capability_ids = [row[0] for row in capability_rows]
        if not capability_ids:
            return {
                "ready": True,
                "gis_enabled": False,
                "project_id": str(project_id),
                "profile": profile,
                "capabilities": [],
                "layers": [],
                "reason": "no_gis_scope_binding",
            }

        placeholders = ",".join(["%s::uuid"] * len(capability_ids))
        cursor.execute(
            f"""
            SELECT
                ft.id::text,
                ft.standard_name,
                ft.physical_name,
                ft.label,
                ft.domain_code,
                ft.geometry_kind,
                bool_or(cf.required) AS required,
                min(COALESCE(NULLIF(cf.sort_order,0),NULLIF(pf.sort_order,0),ft.sort_order)) AS resolved_sort
              FROM gis.capability_feature cf
              JOIN gis.profile_feature pf
                ON pf.feature_type_id=cf.feature_type_id
               AND pf.profile_id=%s::uuid
               AND pf.enabled
              JOIN gis.meta_feature_type ft
                ON ft.id=cf.feature_type_id AND ft.active
             WHERE cf.enabled
               AND cf.capability_id IN ({placeholders})
             GROUP BY ft.id,ft.standard_name,ft.physical_name,ft.label,
                      ft.domain_code,ft.geometry_kind,ft.sort_order
             ORDER BY resolved_sort,ft.standard_name
            """,
            [profile["id"], *capability_ids],
        )
        layer_rows = cursor.fetchall()

    layers = [
        {
            "id": row[0],
            "standard_name": row[1],
            "physical_name": row[2],
            "label": row[3],
            "domain": row[4],
            "geometry_kind": row[5],
            "required": bool(row[6]),
            "sort_order": row[7],
        }
        for row in layer_rows
    ]
    return {
        "ready": True,
        "gis_enabled": bool(layers),
        "project_id": str(project_id),
        "profile": profile,
        "capabilities": capabilities,
        "layers": layers,
        "reason": "ok" if layers else "profile_capability_intersection_empty",
    }


def allowed_standard_names(plan: dict[str, Any]) -> set[str]:
    return {str(row["standard_name"]).upper() for row in plan.get("layers") or []}


def allowed_standard_names_for_projects(alias: str, project_ids) -> set[str]:
    """Resolve the authorized project set's Layer Plan union in one query."""
    scoped_ids = [str(value) for value in project_ids]
    if not scoped_ids or not scope_capability_ready(alias):
        return set()
    with connections[alias].cursor() as cursor:
        cursor.execute(
            """
            WITH requested_projects AS (
                SELECT unnest(%s::uuid[]) AS project_id
            ), selected_profiles AS (
                SELECT rp.project_id,
                       COALESCE(
                           (
                               SELECT pp.profile_id
                                 FROM gis.project_profile pp
                                 JOIN gis.profile p ON p.id=pp.profile_id AND p.active
                                WHERE pp.project_id=rp.project_id AND pp.status='active'
                                LIMIT 1
                           ),
                           (
                               SELECT p.id
                                 FROM gis.profile p
                                WHERE p.code=%s AND p.active
                                LIMIT 1
                           )
                       ) AS profile_id
                  FROM requested_projects rp
            )
            SELECT DISTINCT upper(ft.standard_name)
              FROM prj.scope_item s
              JOIN selected_profiles sp ON sp.project_id=s.project_id
              JOIN gis.scope_binding b
                ON b.active
               AND (
                    (b.catalog_level=2 AND b.catalog_item_id=s.lv2_id) OR
                    (b.catalog_level=3 AND b.catalog_item_id=s.lv3_id) OR
                    (b.catalog_level=4 AND b.catalog_item_id=s.lv4_id)
               )
              JOIN gis.capability c ON c.id=b.capability_id AND c.active
              JOIN gis.capability_feature cf
                ON cf.capability_id=c.id AND cf.enabled
              JOIN gis.profile_feature pf
                ON pf.profile_id=sp.profile_id
               AND pf.feature_type_id=cf.feature_type_id
               AND pf.enabled
              JOIN gis.meta_feature_type ft
                ON ft.id=cf.feature_type_id AND ft.active
             WHERE s.project_id=ANY(%s::uuid[])
            """,
            [scoped_ids, DEFAULT_PROFILE_CODE, scoped_ids],
        )
        return {str(row[0]).upper() for row in cursor.fetchall()}


def require_enabled_layer_plan(plan: dict[str, Any]) -> dict[str, Any]:
    """Fail closed when project GIS metadata or business scope is unavailable."""
    if not plan.get("ready"):
        raise Http404("GIS foundation metadata is not available for this tenant.")
    if not plan.get("gis_enabled"):
        raise Http404("GIS is not enabled by this project's business scope.")
    return plan
