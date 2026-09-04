# GeoFlow QGIS Connector MVP

Status: development-only editable GeoPackage materialization increment.

## Goal

Validate the authoritative chain before QField packaging or server synchronization:

`GeoFlow login -> authorized GIS projects -> business-scope Layer Plan -> project GeoPackage -> QGIS local editing`

GeoFlow Server/PostGIS remains the source of truth. The plugin must not carry tenant-wide database passwords, AWS credentials, or authorization rules.

## Current transport

The connector now uses `server_gpkg_editable_snapshot`.

- QGIS logs in through the existing GeoFlow login/session flow.
- `/gis/api/qgis/projects/` returns only projects that are both visible to the current user and GIS-enabled by project business scope.
- `/gis/projects/<project_id>/api/qgis-manifest/` returns the same Profile/Capability/Layer Plan used by WebGIS plus field-level package metadata.
- `/gis/projects/<project_id>/api/qgis-package/` materializes one project-scoped GeoPackage on demand.
- The GeoPackage contains only Layer Plan layers and only rows whose `project_id` equals the selected project.
- Empty Layer Plan layers are still created with schema so new features can be captured.
- UUID `id` and `project_id` remain GeoFlow identity/scope fields; the local GeoPackage adds `fid INTEGER PRIMARY KEY` only for OGR/QGIS feature editing.
- Tenant PostGIS host/user/password are never returned to QGIS.
- Authorized writers can edit attributes and geometry locally in the downloaded GeoPackage.
- New local features receive a QGIS `uuid()` default and the selected project UUID as default `project_id`.
- System/scope fields are made read-only in the QGIS form when the running QGIS API supports per-field read-only configuration.
- Users without project write authority receive the same package as read-only layers.
- Server synchronization is intentionally disabled in this increment.

The plugin writes each fresh download to a timestamped file under the QGIS application data directory. It never overwrites an earlier locally edited package before synchronization exists.

## Why direct PostGIS remains deferred

A normal saved tenant PostGIS connection would let the desktop client address tenant-wide tables and would make the project subset filter a client responsibility. That violates the GeoFlow authorization invariant.

Direct PostGIS may be introduced only after a separately reviewed project-scoped mechanism such as RLS, project-scoped views/roles, short-lived credentials, or a proxy is implemented. The current GeoPackage transport keeps server authorization authoritative while enabling professional desktop editing.

## Development install

From the GeoFlow repository in PowerShell:

```powershell
.\scripts\dev\install_geoflow_qgis_connector.ps1
```

Default install location:

`%APPDATA%\QGIS\QGIS3\profiles\default\python\plugins\geoflow_connector`

Restart QGIS (or reload plugins), then enable:

`Plugins > Manage and Install Plugins > Installed > GeoFlow Connector`

## Test flow

1. Start the isolated GeoFlow development server with `scripts/dev/start_geoflow_dev.ps1`.
2. Open QGIS 3.x.
3. Run `GeoFlow > GeoFlow Connector`.
4. Server URL: `http://127.0.0.1:8000` for the local development runtime.
5. Log in with the synthetic GeoFlow development account.
6. Verify only authorized GIS-enabled projects appear.
7. Select one project and click `선택 프로젝트 QGIS에 열기`.
8. Verify one GeoPackage download creates only the server Layer Plan for that project.
9. For a write-authorized project, open the attribute table and start editing. Confirm attribute edits, point movement, line vertex edits, and new feature creation work locally.
10. Confirm there is no GeoFlow server sync action yet; local edits must remain local in this increment.

Expected matrix after the real-catalog scope reconciliation:

- GIS-DEV-001: WATER + SEWER, 19 layers
- GIS-DEV-002: WATER, 11 layers
- GIS-DEV-003: SEWER, 10 layers
- GIS-DEV-004: absent from the QGIS project list
- GIS-DEV-005: ROAD, 1 layer
- GIS-DEV-006: WATER with three L3 processes, still 11 layers

## Next increment

After editable GeoPackage materialization is proven in QGIS:

1. Define the server sync change-set contract using UUID identity and project scope.
2. Detect created/updated/deleted local rows without trusting client scope values.
3. Revalidate user permission, Layer Plan, allowed fields, UUID, and geometry on GeoFlow Server before PostGIS mutation.
4. Materialize richer metadata/profile form widgets, code/value relations, styles, labels, snapping, and validation rules.
5. Reuse the same project package/profile for QField offline packaging and synchronization.

Do not add QField-specific schema or duplicate layer-selection rules.
