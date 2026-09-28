"""Read-only inventory before the photo catalogue v2 central reset."""
from __future__ import annotations

import json
import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "geoflow_project.settings")

import django

django.setup()

from django.db import connections

from control.models import GroupDBConfig
from control.services.gis_admin import tenant_cursor


def scalar(cursor, query, params=None):
    cursor.execute(query, params or [])
    return int(cursor.fetchone()[0])


with connections["default"].cursor() as cursor:
    central = {}
    for table in ("photo_template", "photo_slot", "photo_policy"):
        central[table] = scalar(cursor, f"SELECT count(*) FROM gis.{table}")

tenants = []
configs = (GroupDBConfig.objects.using("default").select_related("group")
           .filter(group__status="active").exclude(db_alias="default").order_by("group_id"))
for config in configs:
    with tenant_cursor(config.group_id, write=False) as cursor:
        rows = scalar(cursor, "SELECT count(*) FROM gis.feature_photo")
        live_rows = scalar(cursor, "SELECT count(*) FROM gis.feature_photo WHERE deleted_at IS NULL")
        object_keys = scalar(cursor, """SELECT count(DISTINCT object_key)
            FROM gis.feature_photo WHERE object_key IS NOT NULL AND object_key <> ''""")
    tenants.append({
        "tenant_code": config.group.code,
        "feature_photo_rows": rows,
        "live_feature_photo_rows": live_rows,
        "referenced_s3_object_keys": object_keys,
        "planned_row_deletions": 0,
        "planned_s3_deletions": 0,
    })

print("GIS_PHOTO_CATALOG_V2_INVENTORY=" + json.dumps({
    "central_rows_to_reset": central,
    "tenant_photos_preserved": tenants,
    "planned_tenant_photo_deletions": 0,
    "planned_s3_deletions": 0,
}, ensure_ascii=False, sort_keys=True))
