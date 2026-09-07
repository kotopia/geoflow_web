# GeoFlow QGIS Connector MVP

Status: development-only editable GeoPackage + guarded server sync increment.

## Goal

Validate the authoritative desktop-editing chain before QField packaging:

`GeoFlow login -> authorized GIS projects -> business-scope Layer Plan -> project GeoPackage -> QGIS editing -> guarded GeoFlow sync`

GeoFlow Server/PostGIS remains the source of truth. The plugin never carries tenant-wide database passwords, AWS credentials, or authorization rules.

## Current transport

The connector uses `server_gpkg_editable_snapshot`.

- QGIS logs in through the existing GeoFlow login/session flow.
- `/gis/api/qgis/projects/` returns only projects that are both visible to the current user and GIS-enabled by project business scope.
- `/gis/projects/<project_id>/api/qgis-manifest/` returns the same Profile/Capability/Layer Plan used by WebGIS plus field-level package metadata.
- `/gis/projects/<project_id>/api/qgis-package/` materializes one project-scoped GeoPackage on demand.
- `/gis/projects/<project_id>/api/qgis-sync/` accepts an edited GeoPackage only when the current user has project write authority and the server is running in the strict dev/test runtime.
- The GeoPackage contains only Layer Plan layers and only rows whose `project_id` equals the selected project.
- Empty Layer Plan layers are still created with schema so new features can be captured.
- UUID `id` and `project_id` remain GeoFlow identity/scope fields; the local GeoPackage adds `fid INTEGER PRIMARY KEY` only for OGR/QGIS feature editing.
- Tenant PostGIS host/user/password are never returned to QGIS.
- Authorized writers can edit attributes and geometry locally in the downloaded GeoPackage.
- New local features receive a QGIS `uuid()` default and the selected project UUID as default `project_id`.
- Audit timestamps remain server-authoritative and are not trusted from the desktop package.
- Users without project write authority receive the package as read-only layers and no sync URL.

The package embeds private GeoFlow baseline metadata that is not registered as QGIS feature layers:

- project UUID / profile context
- each original feature UUID
- the original local `fid` used to prevent UUID identity rewriting
- the server `updated_at` value used for optimistic conflict detection

## Sync behavior

When the user chooses `GeoFlow에 동기화`:

1. The plugin commits any still-open QGIS edit sessions to the local GeoPackage.
2. The complete project GeoPackage is uploaded through the authenticated GeoFlow session.
3. GeoFlow recomputes the current user's project permission and current Layer Plan; client layer scope is not trusted.
4. GeoFlow compares the package against its embedded baseline:
   - UUID absent from baseline -> create
   - baseline UUID absent from current package -> delete
   - baseline/current UUID both present with changed editable attributes or geometry -> update
5. `id`, `project_id`, audit fields, non-editable fields, geometry type/validity, and Layer Plan are revalidated server-side.
6. Before update/delete, current server `updated_at` must still match the package baseline. A mismatch returns HTTP 409 and the whole sync transaction is rolled back.
7. On success, all changes are committed atomically to the tenant PostGIS DB.
8. The plugin immediately re-materializes a fresh GeoPackage so the next edit cycle starts from new server baseline values.

Current sync is intentionally gated by all of the following:

- Django `DEBUG=True`
- `GEOFLOW_DEV_RUNTIME_STRICT=1`
- physical tenant DB name contains `dev` or `test`
- authenticated user has project write authority

Production synchronization remains disabled pending separate architecture/security approval.

## Why direct PostGIS remains deferred

A normal saved tenant PostGIS connection would let the desktop client address tenant-wide tables and would make the project subset filter a client responsibility. That violates the GeoFlow authorization invariant.

Direct PostGIS may be introduced only after a separately reviewed project-scoped mechanism such as RLS, project-scoped views/roles, short-lived credentials, or a proxy is implemented. The GeoPackage transport keeps server authorization authoritative while enabling professional desktop editing.

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
2. Open QGIS 3.x and run `GeoFlow > GeoFlow Connector`.
3. Log in and select a GIS-enabled project.
4. Confirm one GeoPackage download creates only the server Layer Plan for that project.
5. Edit one existing attribute or geometry and save it locally.
6. Add one new point/line feature and save it locally.
7. Optionally delete one synthetic feature.
8. Click `GeoFlow에 동기화`.
9. Confirm the result reports create/update/delete counts and the project is automatically reopened from a fresh package.
10. Verify the same objects are visible from GeoFlow/WebGIS or by reopening the project in QGIS.

Expected project matrix:

- GIS-DEV-001: WATER + SEWER, 19 layers
- GIS-DEV-002: WATER, 11 layers
- GIS-DEV-003: SEWER, 10 layers
- GIS-DEV-004: absent from the QGIS project list
- GIS-DEV-005: ROAD, 1 layer
- GIS-DEV-006: WATER with three L3 processes, still 11 layers

## Next increment

After this sync contract is proven end-to-end:

1. Add durable GIS change/audit history rather than relying only on table `updated_at`.
2. Materialize richer metadata/profile form widgets, code/value relations, styles, labels, snapping, and validation rules.
3. Define production-grade project-scoped synchronization/security transport.
4. Reuse the same project package/profile for QField offline packaging and synchronization.

Do not add QField-specific schema or duplicate layer-selection rules.
