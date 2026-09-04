# GeoFlow development test server runbook

Status date: 2026-09-04

## Purpose

Build an isolated GeoFlow test server in parallel with the `geoflow_dev` tenant-shaped development database.

The target development shape is:

```text
non-production central/auth DB
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
  fin   (when present in the selected source tenant)
  gis   (new GIS foundation)
```

`geoflow_dev` is the development tenant database. It receives the existing tenant schema definitions and the new `gis` schema. Production tenant databases are not used for GIS schema experiments.

## Database bootstrap

Use `docs/development/gis-dev-db-bootstrap.md` and `scripts/dev/bootstrap_geoflow_dev.ps1`.

The current bootstrap is deliberately schema-only:

- reads an existing stable tenant DB,
- copies `ctr`, `hr`, `prj`, `ops`, and `fin` when present,
- does not copy production business rows,
- applies `docs/architecture/gis-schema-foundation.sql`,
- verifies PostGIS and the resulting schemas.

After bootstrap, seed synthetic test organization/project/employee rows rather than copying production personal/business data by default.

## Test server isolation

Use a separate application checkout, virtual environment, service, socket, environment file, and Nginx upstream from production.

Recommended layout:

```text
/srv/geoflow-dev/current
/srv/geoflow-dev/venv
/run/geoflow-dev/gunicorn.sock
/etc/geoflow/geoflow-dev.env
```

Do not reuse the production `/srv/geoflow/current`, `/srv/geoflow/venv`, `/run/geoflow/gunicorn.sock`, or production environment file.

## Central DB boundary

GeoFlow login/auth and tenant selection depend on the central control DB. A fully isolated shared test server must therefore use a **non-production central/auth database** as well.

Do not point the test server at the production central DB for normal interactive testing, because login/session/account flows can write central records even when the tenant DB is `geoflow_dev`.

Until the non-production central/auth path is ready, `geoflow_dev` can still be used for:

- PostGIS/schema rehearsal,
- Django database-level tests that explicitly select the development tenant connection,
- GIS DDL/model tests,
- QGIS direct development tests using approved development credentials,
- import/export and spatial performance tests.

## Runtime environment

Use `deploy/env/geoflow-dev.env.example` only as a key-name template. Store the actual environment outside Git and restrict permissions.

Important test tenant settings:

```text
TENANT_DB_NAME=geoflow_dev
TENANT_DB_HOST=<RDS endpoint>
TENANT_DB_PORT=5432
```

The Django alias may remain `cheonan_db`; the alias name and physical database name do not need to be identical. `TENANT_DB_NAME=geoflow_dev` is sufficient for the static development connection path.

## Service and proxy templates

- `deploy/systemd/geoflow-dev.service.example`
- `deploy/nginx/geoflow-dev.conf.example`

These are examples only. Review host paths, hostname/TLS topology, permissions, and environment ownership before installation.

## Deployment sequence

1. Bootstrap `geoflow_dev` and verify `ctr/hr/prj/ops/(fin)/gis`.
2. Create a dedicated test-server host or isolated service environment.
3. Install the reviewed Python runtime, GeoDjango native libraries, Nginx, and systemd service requirements.
4. Check out the reviewed GIS topic/release commit into `/srv/geoflow-dev/current`.
5. Create `/srv/geoflow-dev/venv` and install `requirements.txt`.
6. Create the host-owned `/etc/geoflow/geoflow-dev.env`; never commit it.
7. Run `python -m pip check` and `python manage.py check` with the development environment.
8. Run focused GIS/tests without applying production migrations.
9. Collect static assets into the isolated development checkout.
10. Validate and install the development systemd/Nginx configuration.
11. Start only the development service and verify the development socket.
12. Run test-server smoke checks.
13. Only after the non-production central/auth DB is configured, enable shared login/tenant-selection testing.

## Safety rules

- Never run the dev bootstrap against a target DB whose name does not contain `dev` or `test`.
- Never use the bootstrap script to drop production schemas.
- Do not copy production business rows by default.
- Do not reuse production secrets in the test-server environment unless separately reviewed and explicitly required.
- Do not make `geoflow_dev` a production tenant target.
- Database schema changes are rehearsed in `geoflow_dev` before any production-tenant migration is proposed.

## Next GIS increment

After the development DB and test server base are working:

1. create the approved initial WTL/SWL physical tables from `DB테이블--.xlsx`,
2. load GIS code/reference metadata,
3. seed synthetic project/employee data,
4. connect the GIS dashboard to physical tables,
5. test WebGIS edit flows,
6. generate/materialize QGIS project/profile configuration,
7. test QField offline workflow,
8. only then prepare a production-tenant migration plan.
