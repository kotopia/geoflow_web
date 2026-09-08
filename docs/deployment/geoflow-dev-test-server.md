# GeoFlow development test server runbook

Status date: 2026-09-04

## Purpose

Build an isolated GeoFlow test server using separate non-production central/auth and tenant databases.

```text
geoflow_control_dev
        |
        v
GeoFlow test server
        |
        v
geoflow_dev
  ctr
  hr
  prj
  ops
  fin
  gis
```

`geoflow_dev` is the tenant-shaped GIS development DB. `geoflow_control_dev` is the isolated central/auth DB used for login, session, tenant membership, role/permission, and tenant-selection tests.

## Completed tenant GIS foundation

The current development tenant contains:

- cloned schema definitions for `ctr/hr/prj/ops/fin`,
- `gis` foundation tables,
- 17 WTL/SWL physical facility tables,
- 19 active GIS feature types including `DORO` and `SURVEY`,
- metadata/profile seed derived from actual physical columns,
- synthetic contract/project/GIS objects using UUID identity,
- `ftr_idn` retained only as an optional external/legacy identifier.

No production business rows were copied.

## Non-production central/auth DB

Use:

- `scripts/dev/bootstrap_geoflow_control_dev.ps1`
- `docs/development/geoflow-control-dev-seed.sql`
- `scripts/dev/seed_geoflow_control_dev.ps1`

The bootstrap:

1. verifies PostgreSQL client/server compatibility,
2. optionally creates `geoflow_control_dev` only with explicit `-CreateTarget`,
3. requires a fresh dev/test target,
4. copies the source central `public` schema definitions only,
5. copies only non-personal authorization catalog rows from:
   - `roles`
   - `permissions`
   - `role_permissions`
6. does **not** copy users, memberships, groups, sessions, join requests, or tenant DB secrets.

The synthetic central seed creates one verified test user, one active test group, `tenant_admin` membership, and a static tenant route. It requires the copied authz catalog to already include `tenant_admin -> maps.view`.

The test-login password is prompted securely at runtime and is not stored in Git. `group_db_config` stores only static-environment placeholders because the actual tenant DB credentials come from the test-server environment.

## Runtime DB routing

The current application keeps the static Django tenant alias `cheonan_db`. For test runtime:

```text
default     -> physical geoflow_control_dev
cheonan_db  -> physical geoflow_dev
```

Therefore the runtime environment uses:

```text
CENTRAL_DB_NAME=geoflow_control_dev
TENANT_DB_NAME=geoflow_dev
TENANT_DB_REQUIRE_SECRET_REFERENCES=False
```

The alias and physical DB name are intentionally separate concepts.

## Test server isolation

Use a separate application checkout, virtual environment, service, socket, environment file, and Nginx upstream from production.

Recommended Linux layout:

```text
/srv/geoflow-dev/current
/srv/geoflow-dev/venv
/run/geoflow-dev/gunicorn.sock
/etc/geoflow/geoflow-dev.env
```

Do not reuse production `/srv/geoflow/current`, `/srv/geoflow/venv`, `/run/geoflow/gunicorn.sock`, or the production runtime environment file.

## Runtime environment

Use `deploy/env/geoflow-dev.env.example` only as a key-name template. Store real secrets only in the host-owned runtime environment and restrict file permissions.

The test runtime must use non-production central and tenant database names.

## Runtime preflight

After environment variables are loaded, run:

```powershell
.\scripts\dev\check_geoflow_dev_runtime.ps1
```

or the same Django checks from the Linux test-server shell.

The preflight verifies:

- `python manage.py check`,
- `default` physically connects to `geoflow_control_dev`,
- static tenant alias `cheonan_db` physically connects to `geoflow_dev`,
- PostGIS is available,
- 19 active feature types exist,
- field metadata exists,
- synthetic project `GIS-DEV-001` exists,
- representative GIS object counts are readable.

## Service and proxy templates

- `deploy/systemd/geoflow-dev.service.example`
- `deploy/nginx/geoflow-dev.conf.example`
- `deploy/env/geoflow-dev.env.example`

These are templates only. Review host paths, hostname/TLS topology, permissions, and environment ownership before installation.

## Deployment sequence

1. Bootstrap and verify `geoflow_dev`.
2. Apply WTL/SWL physical feature tables.
3. Apply GIS metadata/profile seed.
4. Seed synthetic tenant/GIS development data.
5. Bootstrap `geoflow_control_dev` schema + authz catalog only.
6. Seed synthetic central login/group/membership.
7. Configure the development runtime environment.
8. Run `python -m pip check` and `python manage.py check`.
9. Run `scripts/dev/check_geoflow_dev_runtime.ps1` or equivalent Linux preflight.
10. Open `/gis/` with the synthetic login and verify physical readiness/object counts.
11. Collect static assets into the isolated development checkout.
12. Validate/install the development systemd/Nginx configuration.
13. Start only the development service and verify its socket/HTTP endpoint.
14. Continue to WebGIS edit flows, then QGIS/QField materialization.

## Safety rules

- Never point the shared test server at the production central DB.
- Never run dev/test bootstrap scripts against DB names lacking `dev` or `test`.
- Never copy production users or business rows by default.
- Never store real tenant DB passwords in Git or synthetic central metadata.
- Never make `geoflow_dev` a production tenant target.
- Keep production provisioning disabled in the test runtime.
- Rehearse all schema changes in `geoflow_dev` before any production migration proposal.

## Next GIS increment after runtime verification

1. activate the existing WebGIS map area for the selected synthetic project,
2. load project-scoped WTL/SWL layers from `gis.*`,
3. add create/update API paths using UUID `id`,
4. materialize metadata/profile into QGIS project configuration,
5. test QField offline sync and photo workflows,
6. only then prepare production-tenant migration planning.
