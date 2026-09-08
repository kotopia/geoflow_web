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
    throw "Safety stop: TargetDb must contain dev/test. Current value: $TargetDb"
}

$psql = Resolve-Psql
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$sqlFile = Join-Path $repoRoot "docs\development\gis-dev-scope-matrix-seed.sql"
if (-not (Test-Path $sqlFile)) { throw "GIS scope matrix seed SQL not found: $sqlFile" }

$previousClientEncoding = $env:PGCLIENTENCODING
$env:PGCLIENTENCODING = "UTF8"
try {
    Write-Host "[1/3] Verify scope/capability metadata..." -ForegroundColor Cyan
    & $psql -X -v ON_ERROR_STOP=1 -h $HostName -p $Port -U $DbUser -d $TargetDb -c "SELECT current_database(); SELECT count(*) AS capabilities FROM gis.capability; SELECT to_regclass('gis.scope_binding') AS scope_binding, to_regclass('gis.project_profile') AS project_profile;"
    if ($LASTEXITCODE -ne 0) { throw "GIS scope matrix preflight failed." }

    Write-Host "[2/3] Seed multi-contract/project business-scope matrix..." -ForegroundColor Cyan
    & $psql -X -v ON_ERROR_STOP=1 -h $HostName -p $Port -U $DbUser -d $TargetDb -f $sqlFile
    if ($LASTEXITCODE -ne 0) { throw "GIS scope matrix seed failed." }

    Write-Host "[3/3] Verify project/capability matrix..." -ForegroundColor Green
    & $psql -X -v ON_ERROR_STOP=1 -h $HostName -p $Port -U $DbUser -d $TargetDb -c "WITH cap AS (SELECT DISTINCT s.project_id,c.code FROM prj.scope_item s JOIN gis.scope_binding b ON b.active AND ((b.catalog_level=2 AND b.catalog_item_id=s.lv2_id) OR (b.catalog_level=3 AND b.catalog_item_id=s.lv3_id) OR (b.catalog_level=4 AND b.catalog_item_id=s.lv4_id)) JOIN gis.capability c ON c.id=b.capability_id AND c.active) SELECT p.code,p.name,COALESCE(string_agg(cap.code,',' ORDER BY cap.code),'NO_GIS') AS capabilities FROM prj.projects p LEFT JOIN cap ON cap.project_id=p.id WHERE p.code LIKE 'GIS-DEV-00%' GROUP BY p.code,p.name ORDER BY p.code;"
    if ($LASTEXITCODE -ne 0) { throw "GIS scope matrix verification failed." }

    Write-Host "GeoFlow GIS multi-project scope matrix seed completed successfully." -ForegroundColor Green
    Write-Host "Expected: 001 WATER+SEWER, 002 WATER, 003 SEWER, 004 NO_GIS, 005 ROAD, 006 SURVEY." -ForegroundColor Green
}
finally {
    if ($null -eq $previousClientEncoding) {
        Remove-Item Env:PGCLIENTENCODING -ErrorAction SilentlyContinue
    } else {
        $env:PGCLIENTENCODING = $previousClientEncoding
    }
}
