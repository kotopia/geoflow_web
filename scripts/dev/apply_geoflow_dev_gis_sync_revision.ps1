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

    throw "psql.exe was not found. Set PG_BIN to the PostgreSQL bin directory first."
}

if ($TargetDb -notmatch '(?i)(dev|test)') {
    throw "Safety stop: TargetDb must contain 'dev' or 'test'. Current value: $TargetDb"
}

$psql = Resolve-Psql
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$sqlFile = Join-Path $repoRoot "docs\architecture\gis-sync-revision-v1.sql"

if (-not (Test-Path $sqlFile)) {
    throw "GIS sync revision DDL not found: $sqlFile"
}

Write-Host "[1/4] Verify target and GIS foundation..." -ForegroundColor Cyan
$ready = (& $psql -X -At -v ON_ERROR_STOP=1 -h $HostName -p $Port -U $DbUser -d $TargetDb -c "SELECT (to_regclass('prj.projects') IS NOT NULL AND to_regclass('gis.meta_feature_type') IS NOT NULL)::int;" | Out-String).Trim()
if ($LASTEXITCODE -ne 0 -or $ready -ne '1') {
    throw "GIS foundation is incomplete. Bootstrap geoflow_dev before applying sync revision support."
}

Write-Host "[2/4] Apply Changeset/Revision support DDL..." -ForegroundColor Cyan
& $psql -X -v ON_ERROR_STOP=1 -h $HostName -p $Port -U $DbUser -d $TargetDb -f $sqlFile
if ($LASTEXITCODE -ne 0) { throw "GIS sync revision DDL failed." }

Write-Host "[3/4] Verify support tables..." -ForegroundColor Cyan
$verifySql = @"
SELECT to_regclass('gis.project_sync_state') AS project_sync_state,
       to_regclass('gis.changeset_receipt') AS changeset_receipt,
       to_regclass('gis.feature_change_log') AS feature_change_log;
SELECT count(*) AS project_sync_state_rows FROM gis.project_sync_state;
"@
& $psql -X -v ON_ERROR_STOP=1 -h $HostName -p $Port -U $DbUser -d $TargetDb -c $verifySql
if ($LASTEXITCODE -ne 0) { throw "GIS sync revision verification failed." }

$count = (& $psql -X -At -v ON_ERROR_STOP=1 -h $HostName -p $Port -U $DbUser -d $TargetDb -c "SELECT ((to_regclass('gis.project_sync_state') IS NOT NULL)::int + (to_regclass('gis.changeset_receipt') IS NOT NULL)::int + (to_regclass('gis.feature_change_log') IS NOT NULL)::int);" | Out-String).Trim()
if ($LASTEXITCODE -ne 0 -or $count -ne '3') {
    throw "Expected all 3 GIS sync support tables but verified count=$count."
}

Write-Host "[4/4] Completed." -ForegroundColor Green
Write-Host "geoflow_dev now has project revision, idempotency receipt, and feature change-log support." -ForegroundColor Green
Write-Host "No production DB was touched. No Django migration was run." -ForegroundColor Green
