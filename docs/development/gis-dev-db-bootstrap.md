# GeoFlow GIS development database bootstrap

## Purpose

Create a safe development tenant database inside the existing GeoFlow RDS instance without copying production business rows.

Target example: `geoflow_dev`.

The bootstrap process:

1. verifies the target DB and PostGIS,
2. copies **schema definitions only** from an existing stable tenant DB (`ctr`, `hr`, `prj`, `ops`, and `fin` when present),
3. restores those definitions into the fresh development DB,
4. applies `docs/architecture/gis-schema-foundation.sql`,
5. verifies the resulting schemas/tables.

It does **not** copy tenant business rows.

## Preconditions

- A fresh PostgreSQL database such as `geoflow_dev` already exists on the GeoFlow RDS instance.
- PostGIS is enabled in that target DB and `SELECT PostGIS_Version();` succeeds.
- PostgreSQL client tools `psql`, `pg_dump`, and `pg_restore` are installed on the workstation running the script.
- The DB account can read schema definitions from the source tenant DB and create schemas/tables in the target development DB.
- Run from the repository branch containing `scripts/dev/bootstrap_geoflow_dev.ps1` and the GIS foundation SQL.

## Recommended execution

From PowerShell at the repository root:

```powershell
.\scripts\dev\bootstrap_geoflow_dev.ps1 `
  -HostName "<RDS_ENDPOINT>" `
  -DbUser "<DB_USER>" `
  -SourceDb "cheonan_db" `
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

The WTL/SWL physical facility tables are added in the next reviewed increment after the `DB테이블--.xlsx`, municipal table definition, and code mapping are converted into the final field DDL.

## Why schema-only cloning is used

The GIS model references the existing GeoFlow project and employee domains. Building substitute `ctr/hr/prj/ops` tables by hand would allow the test DB to drift away from the real tenant architecture. Schema-only cloning keeps the development DB structurally compatible while avoiding production business data.

## Next increment

After this bootstrap succeeds:

1. seed synthetic development organization/project/employee rows,
2. create the first WTL/SWL physical facility tables,
3. load `meta_feature_type` / field metadata / code groups,
4. test legacy PostGIS -> GeoFlow mapping (`project_code` -> project UUID, worker name -> employee UUID),
5. connect the read-only GIS dashboard to the physical tables,
6. rehearse QGIS/QField project materialization and project-scoped loading.
