# GeoFlow QGIS Connector MVP

Status: development-only first materialization increment.

## Goal

Validate the authoritative chain before building QField packaging or general WebGIS editing:

`GeoFlow login -> authorized GIS projects -> business-scope Layer Plan -> QGIS materialization`

GeoFlow Server/PostGIS remains the source of truth. The plugin must not carry tenant-wide database passwords, AWS credentials, or authorization rules.

## MVP transport

The first connector intentionally uses `server_geojson_snapshot`.

- QGIS logs in through the existing GeoFlow login/session flow.
- `/gis/api/qgis/projects/` returns only projects that are both visible to the current user and GIS-enabled by project business scope.
- `/gis/projects/<project_id>/api/qgis-manifest/` returns the same Profile/Capability/Layer Plan used by WebGIS.
- Each manifest layer points to the existing server-authorized project GeoJSON endpoint.
- Server-side project authorization and Layer Plan checks remain authoritative.
- Tenant PostGIS host/user/password are not returned to QGIS.
- The plugin materializes snapshots into a `GeoFlow · <project code>` group and marks them read-only.
- If the current 5,000-feature snapshot limit truncates a layer, the plugin fails closed instead of creating an incomplete project.

This is not the final edit/sync transport.

## Why direct PostGIS is deferred

A normal saved tenant PostGIS connection would let the desktop client address tenant-wide tables and would make the project subset filter a client responsibility. That violates the GeoFlow authorization invariant.

Direct PostGIS may be introduced only after a separately reviewed project-scoped mechanism such as RLS, project-scoped views/roles, short-lived credentials, or a proxy is implemented. Until then, the connector uses server-authorized snapshots.

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
8. Verify the QGIS layer tree contains only the server Layer Plan for that project.

Expected matrix after the real-catalog scope reconciliation:

- GIS-DEV-001: WATER + SEWER, 19 layers
- GIS-DEV-002: WATER, 11 layers
- GIS-DEV-003: SEWER, 10 layers
- GIS-DEV-004: absent from the QGIS project list
- GIS-DEV-005: ROAD, 1 layer
- GIS-DEV-006: WATER with three L3 processes, still 11 layers

## Next increment

After the login/project/materialization contract is proven in QGIS:

1. Define the reviewed editing/sync transport.
2. Materialize metadata/profile field configuration and value relations.
3. Add controlled write/sync behavior.
4. Save/materialize `.qgz` in a stable project workspace.
5. Build QField package generation from the same manifest/profile.

Do not add QField-specific schema or duplicate layer-selection rules.
