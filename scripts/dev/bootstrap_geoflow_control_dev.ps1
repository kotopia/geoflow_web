param(
    [Parameter(Mandatory = $true)]
    [string]$HostName,

    [string]$Port = "5432",

    [Parameter(Mandatory = $true)]
    [string]$DbUser,

    [string]$SourceDb = "geoflow_control",

    [string]$TargetDb = "geoflow_control_dev",

    [switch]$CreateTarget
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

function Get-PgToolMajor([string]$ToolPath) {
    $versionText = (& $ToolPath --version 2>&1 | Out-String).Trim()
    if ($versionText -match '(\d+)(?:\.\d+)*\s*$') { return [int]$Matches[1] }
    throw "Could not parse PostgreSQL tool version: $versionText"
}

function Quote-PgIdentifier([string]$Value) {
    return '"' + $Value.Replace('"', '""') + '"'
}

if ($SourceDb -eq $TargetDb) { throw "SourceDb and TargetDb must be different." }
if ($TargetDb -notmatch '(?i)(dev|test)') {
    throw "Safety stop: TargetDb must contain 'dev' or 'test'. Current value: $TargetDb"
}
if ($TargetDb -notmatch '^[A-Za-z0-9_]+$') {
    throw "Safety stop: TargetDb may contain only letters, numbers, and underscore."
}

$psql = Resolve-PgTool "psql"
$pgDump = Resolve-PgTool "pg_dump"
$pgRestore = Resolve-PgTool "pg_restore"

Write-Host "[1/7] Verify source PostgreSQL version and client compatibility..." -ForegroundColor Cyan
$serverVersionNumText = (& $psql -X -At -v ON_ERROR_STOP=1 -h $HostName -p $Port -U $DbUser -d $SourceDb -c "SHOW server_version_num;" | Out-String).Trim()
if ($LASTEXITCODE -ne 0 -or $serverVersionNumText -notmatch '^\d+$') { throw "Could not determine source PostgreSQL version." }
$serverMajor = [int]([math]::Floor(([int64]$serverVersionNumText) / 10000))
$dumpMajor = Get-PgToolMajor $pgDump
$restoreMajor = Get-PgToolMajor $pgRestore
Write-Host "PostgreSQL version check: server=$serverMajor, pg_dump=$dumpMajor, pg_restore=$restoreMajor" -ForegroundColor DarkCyan
if ($dumpMajor -ne $serverMajor -or $restoreMajor -ne $serverMajor) {
    throw "Use PostgreSQL $serverMajor pg_dump/pg_restore for this bootstrap."
}

Write-Host "[2/7] Ensure non-production central target database exists..." -ForegroundColor Cyan
$targetExists = (& $psql -X -At -v ON_ERROR_STOP=1 -h $HostName -p $Port -U $DbUser -d postgres -c "SELECT 1 FROM pg_database WHERE datname='$TargetDb';" | Out-String).Trim()
if ($LASTEXITCODE -ne 0) { throw "Could not inspect target database existence." }
if ($targetExists -ne '1') {
    if (-not $CreateTarget) {
        throw "Target database '$TargetDb' does not exist. Rerun with -CreateTarget to create this dev/test DB explicitly."
    }
    $quotedTarget = Quote-PgIdentifier $TargetDb
    & $psql -X -v ON_ERROR_STOP=1 -h $HostName -p $Port -U $DbUser -d postgres -c "CREATE DATABASE $quotedTarget;"
    if ($LASTEXITCODE -ne 0) { throw "Could not create target database '$TargetDb'." }
}

Write-Host "[3/7] Verify target is a fresh central development DB..." -ForegroundColor Cyan
$existingAppTables = @(& $psql -X -At -v ON_ERROR_STOP=1 -h $HostName -p $Port -U $DbUser -d $TargetDb -c "SELECT tablename FROM pg_tables WHERE schemaname='public' AND tablename IN ('users','groups','roles','permissions','role_permissions','user_group_map','group_db_config') ORDER BY 1;")
if ($LASTEXITCODE -ne 0) { throw "Could not inspect target public schema." }
$existingAppTables = @($existingAppTables | Where-Object { $_ -and $_.Trim() })
if ($existingAppTables.Count -gt 0) {
    throw "Safety stop: target already contains central application tables: $($existingAppTables -join ', '). Use a fresh dev/test central DB."
}

Write-Host "[4/7] Mirror reviewed shared extensions from source central DB..." -ForegroundColor Cyan
$sourceExtensions = @(& $psql -X -At -v ON_ERROR_STOP=1 -h $HostName -p $Port -U $DbUser -d $SourceDb -c "SELECT extname FROM pg_extension WHERE extname IN ('citext','pgcrypto') ORDER BY extname;")
if ($LASTEXITCODE -ne 0) { throw "Could not inspect source central extensions." }
foreach ($ext in ($sourceExtensions | Where-Object { $_ -and $_.Trim() })) {
    $quotedExt = Quote-PgIdentifier $ext.Trim()
    & $psql -X -v ON_ERROR_STOP=1 -h $HostName -p $Port -U $DbUser -d $TargetDb -c "CREATE EXTENSION IF NOT EXISTS $quotedExt WITH SCHEMA public;"
    if ($LASTEXITCODE -ne 0) { throw "Could not create extension '$ext' in target." }
}
# pgcrypto is required for synthetic dev-login password hashing even if source did not use it.
& $psql -X -v ON_ERROR_STOP=1 -h $HostName -p $Port -U $DbUser -d $TargetDb -c 'CREATE EXTENSION IF NOT EXISTS pgcrypto WITH SCHEMA public;'
if ($LASTEXITCODE -ne 0) { throw "Could not ensure pgcrypto in target." }

$tempSchemaDump = Join-Path $env:TEMP ("geoflow-control-schema-{0}.dump" -f ([guid]::NewGuid().ToString('N')))
$tempSchemaList = Join-Path $env:TEMP ("geoflow-control-schema-{0}.list" -f ([guid]::NewGuid().ToString('N')))
$tempCatalogDump = Join-Path $env:TEMP ("geoflow-control-authz-catalog-{0}.dump" -f ([guid]::NewGuid().ToString('N')))
try {
    Write-Host "[5/7] Copy central public schema definitions only..." -ForegroundColor Cyan
    & $pgDump -h $HostName -p $Port -U $DbUser -d $SourceDb --format=custom --schema-only --schema=public --no-owner --no-privileges --file $tempSchemaDump
    if ($LASTEXITCODE -ne 0) { throw "Central schema-only pg_dump failed." }

    # Every new PostgreSQL database already owns a public schema. The source
    # schema-only archive also contains CREATE SCHEMA public, which would fail
    # immediately on restore. citext/pgcrypto were deliberately created above
    # as reviewed shared dependencies, so suppress their duplicate CREATE
    # EXTENSION archive entries as well. Keep all other public objects.
    $restoreList = @(& $pgRestore --list $tempSchemaDump)
    if ($LASTEXITCODE -ne 0) { throw "Could not inspect central schema archive." }
    $filteredRestoreList = @(
        $restoreList | Where-Object {
            $_ -notmatch '\sSCHEMA\s+-\s+public(\s|$)' -and
            $_ -notmatch '\sEXTENSION\s+-\s+(citext|pgcrypto)(\s|$)'
        }
    )
    $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllLines($tempSchemaList, $filteredRestoreList, $utf8NoBom)

    Write-Host "Restoring public objects into the existing target public schema..." -ForegroundColor DarkCyan
    & $pgRestore -h $HostName -p $Port -U $DbUser -d $TargetDb --no-owner --no-privileges --exit-on-error --use-list $tempSchemaList $tempSchemaDump
    if ($LASTEXITCODE -ne 0) { throw "Central schema-only pg_restore failed." }

    Write-Host "[6/7] Copy non-personal authorization catalog only..." -ForegroundColor Cyan
    & $pgDump -h $HostName -p $Port -U $DbUser -d $SourceDb --format=custom --data-only --no-owner --no-privileges --table=public.roles --table=public.permissions --table=public.role_permissions --file $tempCatalogDump
    if ($LASTEXITCODE -ne 0) { throw "Authorization catalog pg_dump failed." }
    & $pgRestore -h $HostName -p $Port -U $DbUser -d $TargetDb --no-owner --no-privileges --exit-on-error $tempCatalogDump
    if ($LASTEXITCODE -ne 0) { throw "Authorization catalog pg_restore failed." }

    Write-Host "[7/7] Verify central development foundation..." -ForegroundColor Green
    & $psql -X -v ON_ERROR_STOP=1 -h $HostName -p $Port -U $DbUser -d $TargetDb -c "SELECT current_database(); SELECT count(*) AS users FROM users; SELECT count(*) AS groups FROM groups; SELECT count(*) AS roles FROM roles; SELECT count(*) AS permissions FROM permissions; SELECT count(*) AS role_permissions FROM role_permissions;"
    if ($LASTEXITCODE -ne 0) { throw "Central development verification failed." }

    Write-Host "GeoFlow non-production central DB bootstrap completed successfully." -ForegroundColor Green
    Write-Host "No production users, memberships, groups, sessions, or tenant DB secrets were copied." -ForegroundColor Green
}
finally {
    if (Test-Path $tempSchemaDump) { Remove-Item $tempSchemaDump -Force }
    if (Test-Path $tempSchemaList) { Remove-Item $tempSchemaList -Force }
    if (Test-Path $tempCatalogDump) { Remove-Item $tempCatalogDump -Force }
}
