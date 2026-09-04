param(
    [Parameter(Mandatory = $true)]
    [string]$HostName,

    [string]$Port = "5432",

    [Parameter(Mandatory = $true)]
    [string]$DbUser,

    [string]$SourceDb = "geoflow_control",

    [string]$TargetDb = "geoflow_control_dev",

    [switch]$ReplaceExisting
)

$ErrorActionPreference = "Stop"

function Resolve-PgTool([string]$Name) {
    if ($env:PG_BIN) {
        $candidate = Join-Path $env:PG_BIN "$Name.exe"
        if (Test-Path $candidate) { return $candidate }
    }
    $cmd = Get-Command $Name -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    throw "$Name.exe was not found. Set PG_BIN to the PostgreSQL 16 bin directory first."
}

if ($SourceDb -eq $TargetDb) { throw "SourceDb and TargetDb must be different." }
if ($TargetDb -notmatch '(?i)(dev|test)') {
    throw "Safety stop: TargetDb must contain dev/test. Current value: $TargetDb"
}

$psql = Resolve-PgTool "psql"
$pgDump = Resolve-PgTool "pg_dump"
$pgRestore = Resolve-PgTool "pg_restore"

$previousClientEncoding = $env:PGCLIENTENCODING
$env:PGCLIENTENCODING = "UTF8"

$tempSchemaDump = Join-Path $env:TEMP ("geoflow-control-catalog-schema-{0}.dump" -f ([guid]::NewGuid().ToString('N')))
$tempDataDump = Join-Path $env:TEMP ("geoflow-control-catalog-data-{0}.dump" -f ([guid]::NewGuid().ToString('N')))

try {
    Write-Host "[1/5] Verify source central catalog..." -ForegroundColor Cyan
    $sourceTable = (& $psql -X -At -v ON_ERROR_STOP=1 -h $HostName -p $Port -U $DbUser -d $SourceDb -c "SELECT to_regclass('catalog.category_node');" | Out-String).Trim()
    if ($LASTEXITCODE -ne 0 -or $sourceTable -ne 'catalog.category_node') {
        throw "Source central catalog.category_node is unavailable."
    }
    $sourceCount = (& $psql -X -At -v ON_ERROR_STOP=1 -h $HostName -p $Port -U $DbUser -d $SourceDb -c "SELECT count(*) FROM catalog.category_node;" | Out-String).Trim()
    if ($LASTEXITCODE -ne 0 -or $sourceCount -notmatch '^\d+$' -or [int64]$sourceCount -le 0) {
        throw "Source central catalog is empty or unreadable."
    }
    Write-Host "Source category_node rows: $sourceCount" -ForegroundColor DarkCyan

    Write-Host "[2/5] Verify target state..." -ForegroundColor Cyan
    $targetCatalog = (& $psql -X -At -v ON_ERROR_STOP=1 -h $HostName -p $Port -U $DbUser -d $TargetDb -c "SELECT to_regnamespace('catalog') IS NOT NULL;" | Out-String).Trim()
    if ($LASTEXITCODE -ne 0) { throw "Could not inspect target catalog schema." }
    if ($targetCatalog -eq 't') {
        if (-not $ReplaceExisting) {
            throw "Target already has catalog schema. Rerun with -ReplaceExisting only if you intend to refresh this non-production reference catalog."
        }
        Write-Host "Replacing existing target catalog schema (development DB only)..." -ForegroundColor Yellow
        & $psql -X -v ON_ERROR_STOP=1 -h $HostName -p $Port -U $DbUser -d $TargetDb -c "DROP SCHEMA catalog CASCADE;"
        if ($LASTEXITCODE -ne 0) { throw "Could not replace target catalog schema." }
    }

    Write-Host "[3/5] Copy catalog schema definitions only..." -ForegroundColor Cyan
    & $pgDump -h $HostName -p $Port -U $DbUser -d $SourceDb --format=custom --schema-only --schema=catalog --no-owner --no-privileges --file $tempSchemaDump
    if ($LASTEXITCODE -ne 0) { throw "Central catalog schema pg_dump failed." }
    & $pgRestore -h $HostName -p $Port -U $DbUser -d $TargetDb --no-owner --no-privileges --exit-on-error $tempSchemaDump
    if ($LASTEXITCODE -ne 0) { throw "Central catalog schema pg_restore failed." }

    Write-Host "[4/5] Copy non-personal catalog reference data..." -ForegroundColor Cyan
    & $pgDump -h $HostName -p $Port -U $DbUser -d $SourceDb --format=custom --data-only --schema=catalog --no-owner --no-privileges --file $tempDataDump
    if ($LASTEXITCODE -ne 0) { throw "Central catalog data pg_dump failed." }
    & $pgRestore -h $HostName -p $Port -U $DbUser -d $TargetDb --no-owner --no-privileges --exit-on-error $tempDataDump
    if ($LASTEXITCODE -ne 0) { throw "Central catalog data pg_restore failed." }

    Write-Host "[5/5] Verify target catalog reference state..." -ForegroundColor Green
    & $psql -X -v ON_ERROR_STOP=1 -h $HostName -p $Port -U $DbUser -d $TargetDb -c "SELECT current_database(); SELECT count(*) AS category_nodes FROM catalog.category_node; SELECT count(*) AS category_parents FROM catalog.category_parent; SELECT count(*) AS facet_options FROM catalog.category_facet_option; SELECT count(*) AS option_sets FROM catalog.category_option_set;"
    if ($LASTEXITCODE -ne 0) { throw "Target central catalog verification failed." }

    Write-Host "GeoFlow central development catalog sync completed successfully." -ForegroundColor Green
    Write-Host "Copied only catalog schema/reference taxonomy. No users, memberships, sessions, or tenant DB secrets were copied." -ForegroundColor Green
}
finally {
    if (Test-Path $tempSchemaDump) { Remove-Item $tempSchemaDump -Force }
    if (Test-Path $tempDataDump) { Remove-Item $tempDataDump -Force }
    if ($null -eq $previousClientEncoding) {
        Remove-Item Env:PGCLIENTENCODING -ErrorAction SilentlyContinue
    } else {
        $env:PGCLIENTENCODING = $previousClientEncoding
    }
}
