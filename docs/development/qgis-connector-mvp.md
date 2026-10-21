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

## Managed production and test repositories

The existing private `geoflow-upload` S3 bucket and Django streaming routes serve
both channels. No public S3 ACL, nginx static directory, CDN or new storage service
is introduced. XML has no-store headers; immutable versioned ZIPs have a one-year
cache lifetime. Public proxy/cache behavior is checked after deployment.

| Channel | Public repository | S3 index | Versioned packages |
| --- | --- | --- | --- |
| Production | https://geoflow.co.kr/gis/qgis/plugins/plugins.xml | qgis-plugins/stable/plugins.xml | qgis-plugins/stable/packages/geoflow_connector-VERSION.zip |
| Test | https://geoflow.co.kr/gis/qgis/plugins/test/plugins.xml | qgis-plugins/test/plugins.xml | qgis-plugins/releases/geoflow_connector-VERSION.zip |

Production download URLs use `/gis/qgis/plugins/packages/`. The Web installation
modal defaults to the production repository and follows its current index for a
direct ZIP download; later releases need no hardcoded Web version update.
The existing `/stable/plugins.xml` alias resolves the same stable index. Test
URLs and package objects remain intact. Normal stable promotion writes only the
stable prefix and verifies the test index remains byte-identical, including over
public HTTP. `tenants/` is never used by plugin publication.

Development → local Codex tests → explicit protected test publisher → final
approval → release lock → protected GIS deployment with stable promotion.
Test publishing is workflow_dispatch only, derives the version from metadata and
retains its existing channel-specific confirmation. A stable-source merge never
automatically overwrites the test index. Reviewers should approve the current
combined GIS deploy run, not a stale pre-transition test-publisher run.

The release promotion descriptor is `docs/operations/qgis-plugin-stable-release.json`.
It pins the source commit, ZIP name, size and SHA256; the existing source release
manifest and file inventory provide independent byte-level checks. The1.4.3 ZIP
was produced on Windows:13 Git-normalized text files are reconstructed only if
their declared file hashes prove the exact CRLF bytes; Windows path ordering and
ZIP creator platform are fixed. Any mismatch prevents publication. New release
origins require a reviewed matching archive profile or the original artifact;
never replace the approved SHA with a convenient local rebuild hash.

The publisher resolves the Django project root from its own file before setup,
so direct deployment and rollback execution do not require a caller-provided
`PYTHONPATH` or a particular working directory.
The stable publisher verifies ZIP CRC, one geoflow_connector root, metadata,
nonexperimental/nondeprecated flags, UTF-8 XML escaping and channel URL. All
immutable objects are read back in full; an existing different ZIP is rejected.
Before replacing the stable XML it saves that XML under
`qgis-plugins/stable/history/plugins-XML_SHA256.xml`; every new index is archived
as well. Previous ZIPs are retained. Publication is serialized by the existing
protected GIS deployment concurrency and a server file lock.

Rollback, while using compatible server routes, is an explicitly protected
publisher operation. On the server, invoke the reviewed Python runtime with:

```sh
PYTHONPATH="$repo" "$repo/.venv/bin/python" scripts/ops/publish_qgis_plugin_repository.py \
  --channel stable --rollback-index-key qgis-plugins/stable/history/plugins-XML_SHA256.xml \
  --confirm PUBLISH_QGIS_PLUGIN:stable:geoflow-upload:qgis-plugins --verify-http
```

Replace XML_SHA256 with a recorded previous index hash. This verifies the prior
package, archives the current index and swaps only stable/plugins.xml. An initial
stable publication may have no previous stable version; test is never used as a
rollback substitute. Existing bucket versioning is not assumed or modified.
No IAM grants are changed; denied access stops the protected publication.

Plugin identity remains file_name=geoflow_connector.zip, so a1.4.2 installation
can recognize stable1.4.3 as an update. The repository version string, compatibility
range3.28–4.99 and download bytes are verified. Actual QGIS4.2.2 clean-profile
install/load/restart evidence is in the1.4.3 handoff; the Work host has no QGIS
application/bindings and cannot claim a fresh graphical Plugin Manager test.
Operational login/CRUD was not repeated for the Connector release.

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
