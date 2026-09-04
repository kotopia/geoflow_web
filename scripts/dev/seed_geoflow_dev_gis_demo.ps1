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
$sqlFile = Join-Path $repoRoot "docs\development\gis-dev-demo-seed.sql"
if (-not (Test-Path $sqlFile)) {
    throw "GIS demo seed SQL not found: $sqlFile"
}

Write-Host "[1/3] Verify development target..." -ForegroundColor Cyan
& $psql -X -v ON_ERROR_STOP=1 -h $HostName -p $Port -U $DbUser -d $TargetDb -c "SELECT current_database(), PostGIS_Version(); SELECT count(*) AS gis_feature_tables FROM information_schema.tables WHERE table_schema='gis' AND table_name LIKE 'wtl_%' OR table_schema='gis' AND table_name LIKE 'swl_%';"
if ($LASTEXITCODE -ne 0) { throw "GIS demo seed preflight failed." }

Write-Host "[2/3] Seed synthetic project and representative GIS objects..." -ForegroundColor Cyan
& $psql -X -v ON_ERROR_STOP=1 -h $HostName -p $Port -U $DbUser -d $TargetDb -f $sqlFile
if ($LASTEXITCODE -ne 0) { throw "GIS demo seed failed." }

Write-Host "[3/3] Verify synthetic project/object counts..." -ForegroundColor Green
& $psql -X -v ON_ERROR_STOP=1 -h $HostName -p $Port -U $DbUser -d $TargetDb -c "SELECT id, code, name, status FROM prj.projects WHERE id='11111111-1111-4111-8111-111111111111'::uuid; SELECT 'survey' AS layer, count(*) FROM gis.survey WHERE project_id='11111111-1111-4111-8111-111111111111'::uuid UNION ALL SELECT 'doro', count(*) FROM gis.doro WHERE project_id='11111111-1111-4111-8111-111111111111'::uuid UNION ALL SELECT 'wtl_pipe_lm', count(*) FROM gis.wtl_pipe_lm WHERE project_id='11111111-1111-4111-8111-111111111111'::uuid UNION ALL SELECT 'wtl_valv_ps', count(*) FROM gis.wtl_valv_ps WHERE project_id='11111111-1111-4111-8111-111111111111'::uuid UNION ALL SELECT 'wtl_manh_ps', count(*) FROM gis.wtl_manh_ps WHERE project_id='11111111-1111-4111-8111-111111111111'::uuid UNION ALL SELECT 'swl_pipe_lm', count(*) FROM gis.swl_pipe_lm WHERE project_id='11111111-1111-4111-8111-111111111111'::uuid UNION ALL SELECT 'swl_manh_ps', count(*) FROM gis.swl_manh_ps WHERE project_id='11111111-1111-4111-8111-111111111111'::uuid ORDER BY layer;"
if ($LASTEXITCODE -ne 0) { throw "GIS demo seed verification failed." }

Write-Host "Synthetic GIS demo seed completed successfully." -ForegroundColor Green
Write-Host "All seeded objects use UUID id as the authoritative identifier; ftr_idn is NULL." -ForegroundColor Green
