"""Bounded read-only production diagnosis for GIS photo relation HTTP 503.

This script intentionally performs no API call, S3 operation, or database write.
It reports only schema/runtime facts needed to diagnose the known project,
definition layer, and feature IDs.
"""
from __future__ import annotations

import json
import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "geoflow_project.settings")

import django

django.setup()

from django.db import connections

from control.models import GroupDBConfig
from control.services.gis_admin import tenant_cursor


PROJECT_ID = "6ba9dd5d-0189-4cda-854a-afa0caf06a27"
LAYER_ID = "eef36f4e-b6bb-4929-8a39-78c77a9fd8f0"
PHYSICAL_NAME = "wtl_pipe_ps"
FEATURE_IDS = (
    "285c1b69-52d1-4e66-9fde-10c2f561e8e5",
    "ce6e216c-a3b1-4e5f-8542-bfe7560a2a27",
)
PHOTO_MIGRATIONS = (
    "0039_gis_feature_photo",
    "0041_gis_feature_photo_edited_representation",
    "0042_gis_feature_photo_image_metadata",
    "0043_gis_feature_photo_catalog_v2",
)
REQUIRED_PHOTO_COLUMNS = {
    "id": "uuid",
    "project_id": "uuid",
    "layer_id": "uuid",
    "feature_id": "uuid",
    "template_id": "uuid",
    "variant_id": "uuid",
    "slot_id": "uuid",
    "title": "text",
    "object_key": "text",
    "original_name": "text",
    "mime_type": "text",
    "size_bytes": "bigint",
    "captured_at": "timestamp with time zone",
    "captured_by": "uuid",
    "extra_data": "jsonb",
    "image_metadata": "jsonb",
    "note": "text",
    "sort_order": "integer",
    "deleted_at": "timestamp with time zone",
}


def rows(cursor, query, params=()):
    cursor.execute(query, params)
    names = [column[0] for column in cursor.description]
    return [dict(zip(names, row)) for row in cursor.fetchall()]


with connections["default"].cursor() as cursor:
    central_layer = rows(
        cursor,
        """
        SELECT id::text,standard_name,physical_name,active
          FROM gis.definition_layer
         WHERE id=%s
        """,
        [LAYER_ID],
    )

report = {
    "mode": "read_only",
    "project_id": PROJECT_ID,
    "layer_id": LAYER_ID,
    "expected_physical_name": PHYSICAL_NAME,
    "central_layer": central_layer,
    "matching_tenants": [],
}

configs = (
    GroupDBConfig.objects.using("default")
    .select_related("group")
    .filter(group__status="active")
    .exclude(db_alias="default")
    .order_by("group_id")
)
for config in configs:
    with tenant_cursor(config.group_id, write=False) as cursor:
        cursor.execute("SELECT to_regclass('prj.projects') IS NOT NULL")
        if not cursor.fetchone()[0]:
            continue
        cursor.execute("SELECT EXISTS(SELECT 1 FROM prj.projects WHERE id=%s)", [PROJECT_ID])
        if not cursor.fetchone()[0]:
            continue

        item = {
            "tenant_alias": config.db_alias,
            "project_exists": True,
            "asset_table_exists": False,
            "feature_photo_table_exists": False,
        }
        cursor.execute("SELECT to_regclass('gis.wtl_pipe_ps')::text")
        item["asset_table_exists"] = cursor.fetchone()[0] == "gis.wtl_pipe_ps"
        cursor.execute("SELECT to_regclass('gis.feature_photo')::text")
        item["feature_photo_table_exists"] = cursor.fetchone()[0] == "gis.feature_photo"

        asset_columns = rows(
            cursor,
            """
            SELECT column_name,data_type,is_nullable
              FROM information_schema.columns
             WHERE table_schema='gis' AND table_name=%s
             ORDER BY ordinal_position
            """,
            [PHYSICAL_NAME],
        )
        asset_column_names = {row["column_name"] for row in asset_columns}
        item["asset_identity_columns"] = sorted(
            asset_column_names.intersection({"id", "project_id", "deleted_at", "is_deleted"})
        )
        feature_select = ["id::text", "project_id::text"]
        if "deleted_at" in asset_column_names:
            feature_select.append("deleted_at::text")
        if "is_deleted" in asset_column_names:
            feature_select.append("is_deleted")
        if item["asset_table_exists"] and {"id", "project_id"}.issubset(asset_column_names):
            feature_rows = rows(
                cursor,
                f"SELECT {','.join(feature_select)} FROM gis.wtl_pipe_ps WHERE id=ANY(%s::uuid[]) ORDER BY id",
                [list(FEATURE_IDS)],
            )
        else:
            feature_rows = []
        by_id = {row["id"]: row for row in feature_rows}
        item["features"] = [
            {
                "id": feature_id,
                "exists": feature_id in by_id,
                "project_matches": (
                    by_id.get(feature_id, {}).get("project_id") == PROJECT_ID
                    if feature_id in by_id
                    else False
                ),
                "deleted_at": by_id.get(feature_id, {}).get("deleted_at"),
                "is_deleted": by_id.get(feature_id, {}).get("is_deleted"),
            }
            for feature_id in FEATURE_IDS
        ]

        photo_columns = rows(
            cursor,
            """
            SELECT column_name,data_type,udt_name,is_nullable,column_default
              FROM information_schema.columns
             WHERE table_schema='gis' AND table_name='feature_photo'
             ORDER BY ordinal_position
            """,
        )
        photo_by_name = {row["column_name"]: row for row in photo_columns}
        item["feature_photo_columns"] = photo_columns
        item["missing_required_columns"] = sorted(set(REQUIRED_PHOTO_COLUMNS) - set(photo_by_name))
        item["type_mismatches"] = sorted(
            name
            for name, expected in REQUIRED_PHOTO_COLUMNS.items()
            if name in photo_by_name and photo_by_name[name]["data_type"] != expected
        )
        if item["feature_photo_table_exists"]:
            cursor.execute(
                "SELECT has_table_privilege(current_user,'gis.feature_photo','SELECT,INSERT,UPDATE')"
            )
            item["runtime_table_privileges"] = bool(cursor.fetchone()[0])
            cursor.execute(
                """
                SELECT count(*)
                  FROM gis.feature_photo
                 WHERE project_id=%s AND layer_id=%s AND feature_id=ANY(%s::uuid[])
                """,
                [PROJECT_ID, LAYER_ID, list(FEATURE_IDS)],
            )
            item["existing_target_photo_rows"] = int(cursor.fetchone()[0])
        else:
            item["runtime_table_privileges"] = False
            item["existing_target_photo_rows"] = None

        cursor.execute("SELECT to_regclass('public.django_migrations') IS NOT NULL")
        if cursor.fetchone()[0]:
            item["photo_migrations"] = rows(
                cursor,
                """
                SELECT name,applied::text
                  FROM django_migrations
                 WHERE app='webgisapp' AND name=ANY(%s::text[])
                 ORDER BY name
                """,
                [list(PHOTO_MIGRATIONS)],
            )
        else:
            item["photo_migrations"] = []

        report["matching_tenants"].append(item)

print("GIS_PHOTO_API_503_DIAGNOSTIC=" + json.dumps(report, ensure_ascii=False, sort_keys=True))
