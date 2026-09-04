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
    throw "psql.exe was not found. Set PG_BIN to the PostgreSQL 16 bin directory first."
}

if ($TargetDb -notmatch '(?i)(dev|test)') {
    throw "Safety stop: TargetDb must contain 'dev' or 'test'. Current value: $TargetDb"
}

$psql = Resolve-Psql
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$sqlFile = Join-Path $repoRoot "docs\architecture\gis-metadata-seed-v0.1.sql"
if (-not (Test-Path $sqlFile)) {
    throw "GIS metadata seed SQL not found: $sqlFile"
}

Write-Host "[1/3] Verify GIS physical tables and metadata foundation..." -ForegroundColor Cyan
& $psql -X -v ON_ERROR_STOP=1 -h $HostName -p $Port -U $DbUser -d $TargetDb -c "SELECT current_database(); SELECT count(*) AS initial_feature_tables FROM information_schema.tables WHERE table_schema='gis' AND table_name IN ('wtl_etc_ps','wtl_fire_ps','wtl_flow_ps','wtl_manh_ps','wtl_pipe_lm','wtl_pipe_ps','wtl_plan_lm','wtl_sply_ls','wtl_valv_ps','swl_conn_ls','swl_etc_ps','swl_manh_ps','swl_pipe_as','swl_pipe_lm','swl_pipe_ps','swl_side_ls','swl_spot_ps');"
if ($LASTEXITCODE -ne 0) { throw "GIS preflight failed." }

Write-Host "[2/3] Apply metadata/profile seed..." -ForegroundColor Cyan
& $psql -X -v ON_ERROR_STOP=1 -h $HostName -p $Port -U $DbUser -d $TargetDb -f $sqlFile
if ($LASTEXITCODE -ne 0) { throw "GIS metadata seed failed." }

Write-Host "[3/3] Verify metadata/profile state..." -ForegroundColor Green
& $psql -X -v ON_ERROR_STOP=1 -h $HostName -p $Port -U $DbUser -d $TargetDb -c "SELECT domain_code, count(*) AS feature_types FROM gis.meta_feature_type WHERE active GROUP BY domain_code ORDER BY domain_code; SELECT count(*) AS field_def_count FROM gis.meta_field_def; SELECT code, name, version, active FROM gis.profile WHERE code='GEOFLOW_DEV_BASE'; SELECT standard_name, physical_name, core_field, description FROM gis.meta_field_def WHERE physical_name IN ('id','ftr_idn','project_id','geom') ORDER BY standard_name, physical_name LIMIT 40;"
if ($LASTEXITCODE -ne 0) { throw "GIS metadata verification failed." }

Write-Host "GeoFlow GIS metadata/profile seed completed successfully." -ForegroundColor Green
Write-Host "UUID id is authoritative; ftr_idn remains an optional external/legacy identifier." -ForegroundColor Green
