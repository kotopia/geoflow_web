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
$sqlFile = Join-Path $repoRoot "docs\architecture\gis-scope-capability-v0.1.sql"
if (-not (Test-Path $sqlFile)) { throw "GIS scope capability SQL not found: $sqlFile" }

$previousClientEncoding = $env:PGCLIENTENCODING
$env:PGCLIENTENCODING = "UTF8"
try {
    Write-Host "[1/3] Verify project scope and GIS metadata foundations..." -ForegroundColor Cyan
    & $psql -X -v ON_ERROR_STOP=1 -h $HostName -p $Port -U $DbUser -d $TargetDb -c "SELECT current_database(); SELECT to_regclass('prj.scope_item') AS scope_item, to_regclass('gis.profile') AS profile, to_regclass('gis.meta_feature_type') AS feature_type;"
    if ($LASTEXITCODE -ne 0) { throw "GIS scope capability preflight failed." }

    Write-Host "[2/3] Apply scope/capability/project-profile metadata..." -ForegroundColor Cyan
    & $psql -X -v ON_ERROR_STOP=1 -h $HostName -p $Port -U $DbUser -d $TargetDb -f $sqlFile
    if ($LASTEXITCODE -ne 0) { throw "GIS scope capability DDL failed." }

    Write-Host "[3/3] Verify capability metadata..." -ForegroundColor Green
    & $psql -X -v ON_ERROR_STOP=1 -h $HostName -p $Port -U $DbUser -d $TargetDb -c "SELECT code,name,active FROM gis.capability ORDER BY sort_order,code; SELECT c.code,count(*) AS feature_count FROM gis.capability c JOIN gis.capability_feature cf ON cf.capability_id=c.id AND cf.enabled GROUP BY c.code ORDER BY c.code;"
    if ($LASTEXITCODE -ne 0) { throw "GIS scope capability verification failed." }

    Write-Host "GeoFlow GIS scope capability metadata completed successfully." -ForegroundColor Green
}
finally {
    if ($null -eq $previousClientEncoding) {
        Remove-Item Env:PGCLIENTENCODING -ErrorAction SilentlyContinue
    } else {
        $env:PGCLIENTENCODING = $previousClientEncoding
    }
}
