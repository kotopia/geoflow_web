from __future__ import annotations

from typing import Any


QGIS_MANIFEST_VERSION = "0.6"
QGIS_TRANSPORT_MODE = "server_gpkg_editable_snapshot"


def build_qgis_manifest(
    *,
    project: dict[str, Any],
    plan: dict[str, Any],
    can_write: bool,
    package_url: str,
    package_layers: list[dict[str, Any]],
    layer_counts: dict[str, int | None] | None = None,
    sync_url: str = "",
    sync_supported: bool = False,
    changeset_url: str = "",
    delta_url: str = "",
    changeset_supported: bool = False,
    current_revision: int = 0,
) -> dict[str, Any]:
    """Build the server-authoritative QGIS GeoPackage manifest."""

    project_id = str(project["id"])
    counts = layer_counts or {}
    layers = []
    for row in package_layers:
        standard_name = str(row["standard_name"])
        layers.append(
            {
                **row,
                "row_count": counts.get(standard_name),
                "primary_key": "id",
                "local_fid": "fid",
                "geometry_column": "geom",
                "source_srid": "EPSG:4326",
            }
        )

    effective_sync = bool(sync_supported and can_write and sync_url)
    effective_changeset = bool(
        changeset_supported and can_write and changeset_url and delta_url
    )
    return {
        "manifest_version": QGIS_MANIFEST_VERSION,
        "transport": {
            "mode": QGIS_TRANSPORT_MODE,
            "server_authoritative": True,
            "direct_postgis_credentials_exposed": False,
            "package_url": package_url,
            "package_format": "GeoPackage",
            "package_downloads_per_open": 1,
            "local_editing_supported": bool(can_write),
            "sync_supported": effective_sync,
            "auto_sync_on_qgis_save": bool(effective_sync or effective_changeset),
            "sync_strategy": "field_patch_last_successful_server_write_wins",
            "sync_url": sync_url if effective_sync else "",
            "changeset_supported": effective_changeset,
            "changeset_url": changeset_url if effective_changeset else "",
            "delta_url": delta_url if effective_changeset else "",
            "current_revision": int(current_revision or 0),
            "preferred_sync_protocol": (
                "changeset_v1" if effective_changeset else "gpkg_diff_fallback"
            ),
            "write_authorized": bool(can_write),
            "note": (
                "The v1 operating model is field-level Changeset write + revision Delta read. "
                "Whole-GeoPackage diff sync remains a gated fallback while the QGIS client transition is completed."
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
            "reason": "roaming_cache_protocol_not_implemented_yet",
        },
    }
