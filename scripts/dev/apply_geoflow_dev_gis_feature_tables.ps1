param(
    [Parameter(Mandatory = $true)]
    [string]$HostName,

    [string]$Port = "5432",

    [Parameter(Mandatory = $true)]
    [string]$DbUser,

    [string]$TargetDb = "geoflow_dev"
)

$ErrorActionPreference = "Stop"

function Resolve-Psql {
    if ($env:PG_BIN) {
        $candidate = Join-Path $env:PG_BIN "psql.exe"
        if (Test-Path $candidate) { return $candidate }
    }

    $cmd = Get-Command psql -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }

    $postgresRoot = Join-Path $env:ProgramFiles "PostgreSQL"
    if (Test-Path $postgresRoot) {
        foreach ($dir in (Get-ChildItem $postgresRoot -Directory -ErrorAction SilentlyContinue | Sort-Object Name -Descending)) {
            $candidate = Join-Path $dir.FullName "bin\psql.exe"
            if (Test-Path $candidate) { return $candidate }
        }
    }

    throw "psql.exe was not found. Set PG_BIN to the PostgreSQL 16 bin directory first."
}

if ($TargetDb -notmatch '(?i)(dev|test)') {
    throw "Safety stop: TargetDb must contain 'dev' or 'test'. Current value: $TargetDb"
}

$psql = Resolve-Psql
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$sqlFile = Join-Path $repoRoot "docs\architecture\gis-initial-feature-tables-v0.1.sql"

if (-not (Test-Path $sqlFile)) {
    throw "GIS feature DDL not found: $sqlFile"
}

Write-Host "[1/4] Verify target and GIS foundation..." -ForegroundColor Cyan
$preflightSql = @"
SELECT current_database() AS db, PostGIS_Version() AS postgis;
SELECT to_regclass('prj.projects') AS projects,
       to_regclass('gis.meta_feature_type') AS meta_feature_type,
       to_regclass('gis.survey') AS survey;
"@
& $psql -X -v ON_ERROR_STOP=1 -h $HostName -p $Port -U $DbUser -d $TargetDb -c $preflightSql
if ($LASTEXITCODE -ne 0) { throw "geoflow_dev GIS preflight failed." }

$foundationReady = (& $psql -X -At -v ON_ERROR_STOP=1 -h $HostName -p $Port -U $DbUser -d $TargetDb -c "SELECT (to_regclass('prj.projects') IS NOT NULL AND to_regclass('gis.meta_feature_type') IS NOT NULL AND to_regclass('gis.survey') IS NOT NULL)::int;" | Out-String).Trim()
if ($LASTEXITCODE -ne 0 -or $foundationReady -ne '1') {
    throw "GIS foundation is incomplete. Bootstrap geoflow_dev before applying physical feature tables."
}

Write-Host "[2/4] Apply initial WTL/SWL physical table DDL..." -ForegroundColor Cyan
& $psql -X -v ON_ERROR_STOP=1 -h $HostName -p $Port -U $DbUser -d $TargetDb -f $sqlFile
if ($LASTEXITCODE -ne 0) { throw "Initial GIS physical table DDL failed." }

Write-Host "[3/4] Verify 17 physical feature tables..." -ForegroundColor Cyan
$verifySql = @"
WITH expected(name) AS (
  VALUES
  ('wtl_etc_ps'),('wtl_fire_ps'),('wtl_flow_ps'),('wtl_manh_ps'),('wtl_pipe_lm'),('wtl_pipe_ps'),('wtl_plan_lm'),('wtl_sply_ls'),('wtl_valv_ps'),
  ('swl_conn_ls'),('swl_etc_ps'),('swl_manh_ps'),('swl_pipe_as'),('swl_pipe_lm'),('swl_pipe_ps'),('swl_side_ls'),('swl_spot_ps')
)
SELECT count(*) AS physical_table_count
FROM expected e
WHERE to_regclass('gis.' || e.name) IS NOT NULL;

SELECT domain_code, count(*) AS feature_type_count
FROM gis.meta_feature_type
WHERE physical_name IN (
  'wtl_etc_ps','wtl_fire_ps','wtl_flow_ps','wtl_manh_ps','wtl_pipe_lm','wtl_pipe_ps','wtl_plan_lm','wtl_sply_ls','wtl_valv_ps',
  'swl_conn_ls','swl_etc_ps','swl_manh_ps','swl_pipe_as','swl_pipe_lm','swl_pipe_ps','swl_side_ls','swl_spot_ps'
)
GROUP BY domain_code
ORDER BY domain_code;
"@
& $psql -X -v ON_ERROR_STOP=1 -h $HostName -p $Port -U $DbUser -d $TargetDb -c $verifySql
if ($LASTEXITCODE -ne 0) { throw "GIS feature verification query failed." }

$count = (& $psql -X -At -v ON_ERROR_STOP=1 -h $HostName -p $Port -U $DbUser -d $TargetDb -c "WITH expected(name) AS (VALUES ('wtl_etc_ps'),('wtl_fire_ps'),('wtl_flow_ps'),('wtl_manh_ps'),('wtl_pipe_lm'),('wtl_pipe_ps'),('wtl_plan_lm'),('wtl_sply_ls'),('wtl_valv_ps'),('swl_conn_ls'),('swl_etc_ps'),('swl_manh_ps'),('swl_pipe_as'),('swl_pipe_lm'),('swl_pipe_ps'),('swl_side_ls'),('swl_spot_ps')) SELECT count(*) FROM expected e WHERE to_regclass('gis.' || e.name) IS NOT NULL;" | Out-String).Trim()
if ($LASTEXITCODE -ne 0 -or $count -ne '17') {
    throw "Expected 17 GIS physical feature tables but verified $count."
}

Write-Host "[4/4] Completed." -ForegroundColor Green
Write-Host "geoflow_dev now has the initial 17 WTL/SWL physical feature tables." -ForegroundColor Green
Write-Host "No production DB was touched and no production business rows were copied." -ForegroundColor Green
