# GeoFlow GIS development database bootstrap

## Purpose

Create a safe tenant-shaped development database inside the existing GeoFlow RDS instance.

Target: `geoflow_dev`.

The bootstrap process:

1. verifies the target DB, PostGIS, and PostgreSQL client/server versions,
2. checks/reset-handles only the known GeoFlow schemas in a dev/test target,
3. detects source tenant schemas (`ctr`, `hr`, `prj`, `ops`, and `fin` when present),
4. mirrors required shared PostgreSQL extensions used by those schemas (`citext`, `pgcrypto`, `uuid-ossp`, `hstore`, `pg_trgm`, `btree_gist` when present),
5. copies **schema definitions only** from the stable tenant DB,
6. restores those definitions into `geoflow_dev`,
7. applies `docs/architecture/gis-schema-foundation.sql`,
8. verifies the resulting schemas/tables/extensions.

The initial bootstrap intentionally does **not** copy production business rows. This keeps `geoflow_dev` structurally compatible with the existing tenant DB while avoiding unnecessary production personal/business data. Synthetic development rows are seeded after the schema is stable.

## Development decision

`geoflow_dev` is the canonical tenant-shaped development DB for the first GIS implementation and the parallel GeoFlow test server.

Expected database shape:

```text
geoflow_dev
  ctr   <- existing tenant schema definition
  hr    <- existing tenant schema definition
  prj   <- existing tenant schema definition
  ops   <- existing tenant schema definition
  fin   <- copied when present in the selected source tenant
  gis   <- new GeoFlow GIS schema
```

The existing business schemas are copied rather than recreated by hand so that GIS project/employee references are tested against the real GeoFlow tenant structure.

## Preconditions

- `geoflow_dev` already exists on the GeoFlow RDS instance.
- PostGIS is enabled in that target DB and `SELECT PostGIS_Version();` succeeds.
- PostgreSQL client tools `psql`, `pg_dump`, and `pg_restore` matching the RDS PostgreSQL major version are installed on the workstation running the script.
- The DB account can read schema definitions/extensions from the source tenant DB and create schemas/tables/extensions in `geoflow_dev`.
- Run from the repository branch containing `scripts/dev/bootstrap_geoflow_dev.ps1` and the GIS foundation SQL.

## Recommended execution

From PowerShell at the repository root:

```powershell
.\scripts\dev\bootstrap_geoflow_dev.ps1 `
  -HostName "<RDS_ENDPOINT>" `
  -DbUser "<DB_USER>" `
  -SourceDb "<STABLE_TENANT_DB>" `
  -TargetDb "geoflow_dev"
```

The PostgreSQL tools prompt for the password. Do not place passwords in Git, screenshots, chat, or the script.

If the PostgreSQL tools are installed but not on PATH, set `PG_BIN`, for example:

```powershell
$env:PG_BIN = "C:\Program Files\PostgreSQL\16\bin"
```

Then run the bootstrap command again.

## Recovering from a known partial restore

The default behavior remains fail-closed: if `geoflow_dev` already contains any GeoFlow schema, the script stops.

If a previous bootstrap attempt failed midway and the target is the known disposable `geoflow_dev`/test DB, rerun with the explicit reset switch:

```powershell
.\scripts\dev\bootstrap_geoflow_dev.ps1 `
  -HostName "<RDS_ENDPOINT>" `
  -DbUser "<DB_USER>" `
  -SourceDb "<STABLE_TENANT_DB>" `
  -TargetDb "geoflow_dev" `
  -ResetPartialTarget
```

`-ResetPartialTarget` drops only these schemas in the dev/test target when they already exist:

```text
gis
fin
ops
prj
hr
ctr
```

It does not drop the database itself and it does not touch the source tenant DB. The switch is rejected indirectly by the target-name safety gate if the target DB name does not contain `dev` or `test`.

## Extension dependency handling

A schema-only dump restricted to `ctr/hr/prj/ops/fin` does not automatically include extensions installed in `public`. This matters for columns such as `public.citext`.

The bootstrap therefore detects and mirrors a reviewed allow-list of shared extensions before restore:

```text
citext
pgcrypto
uuid-ossp
hstore
pg_trgm
btree_gist
```

PostGIS must already exist in `geoflow_dev` and is verified separately at step 1.

## Safety behavior

The script stops when:

- source and target DB names are identical,
- the target DB name does not contain `dev` or `test`,
- the target already contains any of `ctr`, `hr`, `prj`, `ops`, `fin`, `gis` and `-ResetPartialTarget` was not explicitly supplied,
- required source schemas (`ctr`, `hr`, `prj`, `ops`) are missing,
- PostgreSQL dump/restore tools are newer than the server major version and a matching toolset cannot be found,
- required extension creation fails,
- any PostgreSQL command fails.

The script never drops or mutates source tenant schemas/data.

## Expected result

At minimum the target contains:

```text
ctr
hr
prj
ops
fin   # when present in the selected source tenant
gis
```

The `gis` schema initially contains architecture support tables such as:

```text
meta_feature_type
meta_field_def
ref_code_group
ref_code_value
profile
profile_feature
profile_field
survey
survey_link
doro
import_batch
```

The WTL/SWL physical facility tables are added in the next reviewed increment after `DB테이블--.xlsx`, municipal table definitions, and code mapping are converted into final field DDL.

## Why schema-only cloning is the first step

The GIS model references the existing GeoFlow project and employee domains. Building substitute `ctr/hr/prj/ops` tables by hand would allow the test DB to drift away from the real tenant architecture.

Schema-only cloning gives us the correct relations, constraints, table names, and data types without immediately duplicating production business data. After the structure is validated, synthetic rows can represent contracts/projects/employees/settings needed for the GIS/WebGIS/QGIS/QField test workflow.

If a later test specifically requires a realistic production-shaped dataset, that data-copy step must be reviewed separately and should prefer sanitized/minimized data rather than an automatic full production clone.

## Test server connection

The parallel test-server plan is documented in `docs/deployment/geoflow-dev-test-server.md`.

For the tenant connection, the physical DB name is:

```text
TENANT_DB_NAME=geoflow_dev
```

The Django connection alias does not have to be renamed from its current default alias; alias name and PostgreSQL database name are separate concepts.

## Next increment

After this bootstrap succeeds:

1. seed synthetic development organization/project/employee/settings rows,
2. create the first WTL/SWL physical facility tables,
3. load `meta_feature_type` / field metadata / code groups,
4. test legacy PostGIS -> GeoFlow mapping (`project_code` -> project UUID, worker name -> employee UUID),
5. connect the GIS dashboard to the physical tables,
6. rehearse WebGIS editing,
7. materialize QGIS/QField project/profile configuration,
8. run QField offline tests.
