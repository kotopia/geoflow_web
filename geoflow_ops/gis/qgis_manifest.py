from __future__ import annotations

from typing import Any
from urllib.parse import urlencode


QGIS_MANIFEST_VERSION = "0.2"
QGIS_TRANSPORT_MODE = "server_geojson_snapshot"
QGIS_SNAPSHOT_LIMIT = 5000


def build_qgis_manifest(
    *,
    project: dict[str, Any],
    plan: dict[str, Any],
    can_write: bool,
    layer_geojson_path: str,
    layer_counts: dict[str, int | None] | None = None,
) -> dict[str, Any]:
    """Build the server-authoritative QGIS Connector manifest.

    The first connector increment intentionally materializes project-scoped
    GeoJSON snapshots instead of exposing tenant PostGIS credentials. The
    server remains authoritative for tenant/project authorization and layer
    scope. Direct PostGIS transport is a later, separately reviewed concern.

    layer_counts is optional. When a project's layer is known to contain zero
    rows, the connector can create an empty schema placeholder without issuing
    a separate GeoJSON HTTP request. Unknown counts remain fetchable.
    """

    project_id = str(project["id"])
    counts = layer_counts or {}
    layers = []
    for row in plan.get("layers") or []:
        standard_name = str(row["standard_name"])
        query = urlencode({"layer": standard_name, "limit": QGIS_SNAPSHOT_LIMIT})
        row_count = counts.get(standard_name)
        layers.append(
            {
                "standard_name": standard_name,
                "physical_name": row.get("physical_name") or "",
                "label": row.get("label") or standard_name,
                "domain": row.get("domain") or "",
                "geometry_kind": row.get("geometry_kind") or "",
                "required": bool(row.get("required")),
                "primary_key": "id",
                "geometry_column": "geom",
                "source_srid": "EPSG:4326",
                "row_count": row_count,
                "snapshot_required": row_count is None or row_count > 0,
                "snapshot_url": f"{layer_geojson_path}?{query}",
                "snapshot_limit": QGIS_SNAPSHOT_LIMIT,
                "snapshot_editable": False,
            }
        )

    return {
        "manifest_version": QGIS_MANIFEST_VERSION,
        "transport": {
            "mode": QGIS_TRANSPORT_MODE,
            "server_authoritative": True,
            "direct_postgis_credentials_exposed": False,
            "editing_supported": False,
            "write_authorized": bool(can_write),
            "empty_layer_fetch_skip_supported": True,
            "note": (
                "MVP materializes server-authorized project snapshots. "
                "Editing/sync transport is a later reviewed increment."
            ),
        },
        "project": {
            "id": project_id,
            "code": project.get("code") or "",
            "name": project.get("name") or "",
            "status": project.get("status") or "",
        },
        "profile": plan.get("profile"),
        "capabilities": plan.get("capabilities") or [],
        "layers": layers,
        "layer_count": len(layers),
        "qfield": {
            "package_supported": False,
            "reason": "qgis_connector_snapshot_mvp",
        },
    }
