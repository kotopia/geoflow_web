# GeoFlow GIS development database bootstrap

## Purpose

Create a safe tenant-shaped development database inside the existing GeoFlow RDS instance.

Target: `geoflow_dev`.

The bootstrap process:

1. verifies the target DB and PostGIS,
2. copies **schema definitions only** from an existing stable tenant DB (`ctr`, `hr`, `prj`, `ops`, and `fin` when present),
3. restores those definitions into `geoflow_dev`,
4. applies `docs/architecture/gis-schema-foundation.sql`,
5. verifies the resulting schemas/tables.

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
- PostgreSQL client tools `psql`, `pg_dump`, and `pg_restore` are installed on the workstation running the script.
- The DB account can read schema definitions from the source tenant DB and create schemas/tables in `geoflow_dev`.
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

## Safety behavior

The script stops when:

- source and target DB names are identical,
- the target DB name does not contain `dev` or `test`,
- the target already contains any of `ctr`, `hr`, `prj`, `ops`, `fin`, `gis`,
- required source schemas (`ctr`, `hr`, `prj`, `ops`) are missing,
- any PostgreSQL command fails.

The target must therefore be a fresh development DB. The script intentionally does not drop or clean schemas automatically.

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
