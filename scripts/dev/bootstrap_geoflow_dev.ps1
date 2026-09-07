param(
    [Parameter(Mandatory = $true)]
    [string]$HostName,

    [string]$Port = "5432",

    [Parameter(Mandatory = $true)]
    [string]$DbUser,

    [string]$SourceDb = "cheonan_db",

    [string]$TargetDb = "geoflow_dev",

    [switch]$ResetPartialTarget
)

$ErrorActionPreference = "Stop"

function Resolve-PgTool([string]$Name) {
    if ($env:PG_BIN) {
        $candidate = Join-Path $env:PG_BIN "$Name.exe"
        if (Test-Path $candidate) { return $candidate }
    }

    $cmd = Get-Command $Name -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }

    $candidateDirs = @()
    $postgresRoot = Join-Path $env:ProgramFiles "PostgreSQL"
    if (Test-Path $postgresRoot) {
        $candidateDirs += Get-ChildItem $postgresRoot -Directory -ErrorAction SilentlyContinue |
            Sort-Object Name -Descending |
            ForEach-Object { Join-Path $_.FullName "bin" }
    }

    $candidateDirs += @(
        (Join-Path $env:ProgramFiles "pgAdmin 4\runtime"),
        (Join-Path ${env:ProgramFiles(x86)} "pgAdmin 4\runtime"),
        (Join-Path $env:LOCALAPPDATA "Programs\pgAdmin 4\runtime")
    ) | Where-Object { $_ }

    foreach ($dir in $candidateDirs) {
        $candidate = Join-Path $dir "$Name.exe"
        if (Test-Path $candidate) { return $candidate }
    }

    throw "$Name was not found. Install PostgreSQL command-line tools, put PostgreSQL bin on PATH, or set PG_BIN to the directory that contains psql.exe/pg_dump.exe/pg_restore.exe."
}

function Get-PgToolMajor([string]$ToolPath) {
    $versionText = (& $ToolPath --version 2>&1 | Out-String).Trim()
    if ($LASTEXITCODE -ne 0) {
        throw "Could not determine PostgreSQL tool version: $ToolPath"
    }
    if ($versionText -match '(\d+)(?:\.\d+)*\s*$') {
        return [int]$Matches[1]
    }
    throw "Could not parse PostgreSQL tool version: $versionText"
}

function Resolve-CompatiblePgBin([int]$ServerMajor) {
    if ($env:PG_BIN) {
        $dump = Join-Path $env:PG_BIN "pg_dump.exe"
        $restore = Join-Path $env:PG_BIN "pg_restore.exe"
        if ((Test-Path $dump) -and (Test-Path $restore)) {
            if ((Get-PgToolMajor $dump) -eq $ServerMajor -and (Get-PgToolMajor $restore) -eq $ServerMajor) {
                return $env:PG_BIN
            }
        }
    }

    $exact = Join-Path $env:ProgramFiles "PostgreSQL\$ServerMajor\bin"
    if ((Test-Path (Join-Path $exact "pg_dump.exe")) -and (Test-Path (Join-Path $exact "pg_restore.exe"))) {
        return $exact
    }

    $postgresRoot = Join-Path $env:ProgramFiles "PostgreSQL"
    if (Test-Path $postgresRoot) {
        foreach ($dir in (Get-ChildItem $postgresRoot -Directory -ErrorAction SilentlyContinue)) {
            $bin = Join-Path $dir.FullName "bin"
            $dump = Join-Path $bin "pg_dump.exe"
            $restore = Join-Path $bin "pg_restore.exe"
            if ((Test-Path $dump) -and (Test-Path $restore)) {
                try {
                    if ((Get-PgToolMajor $dump) -eq $ServerMajor -and (Get-PgToolMajor $restore) -eq $ServerMajor) {
                        return $bin
                    }
                } catch { }
            }
        }
    }
    return $null
}

function Quote-PgIdentifier([string]$Value) {
    return '"' + $Value.Replace('"', '""') + '"'
}

if ($SourceDb -eq $TargetDb) {
    throw "SourceDb and TargetDb must be different."
}
if ($TargetDb -notmatch '(?i)(dev|test)') {
    throw "Safety stop: TargetDb must contain 'dev' or 'test'. Current value: $TargetDb"
}

$psql = Resolve-PgTool "psql"
$pgDump = Resolve-PgTool "pg_dump"
$pgRestore = Resolve-PgTool "pg_restore"

Write-Host "PostgreSQL client tools (initial):" -ForegroundColor DarkCyan
Write-Host "  psql:       $psql"
Write-Host "  pg_dump:    $pgDump"
Write-Host "  pg_restore: $pgRestore"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$foundationSql = Join-Path $repoRoot "docs\architecture\gis-schema-foundation.sql"
if (-not (Test-Path $foundationSql)) {
    throw "GIS foundation SQL not found: $foundationSql"
}

Write-Host "[1/8] Verify target database, PostGIS, and PostgreSQL server version..." -ForegroundColor Cyan
& $psql -X -v ON_ERROR_STOP=1 -h $HostName -p $Port -U $DbUser -d $TargetDb -c "SELECT current_database() AS db, current_setting('server_version') AS postgres, PostGIS_Version() AS postgis;"
if ($LASTEXITCODE -ne 0) { throw "Target DB/PostGIS verification failed." }

$serverVersionNumText = (& $psql -X -At -v ON_ERROR_STOP=1 -h $HostName -p $Port -U $DbUser -d $TargetDb -c "SHOW server_version_num;" | Out-String).Trim()
if ($LASTEXITCODE -ne 0 -or $serverVersionNumText -notmatch '^\d+$') {
    throw "Could not determine PostgreSQL server version."
}
$serverMajor = [int]([math]::Floor(([int64]$serverVersionNumText) / 10000))
$dumpMajor = Get-PgToolMajor $pgDump
$restoreMajor = Get-PgToolMajor $pgRestore

Write-Host "PostgreSQL version check: server=$serverMajor, pg_dump=$dumpMajor, pg_restore=$restoreMajor" -ForegroundColor DarkCyan
if ($dumpMajor -gt $serverMajor -or $restoreMajor -gt $serverMajor) {
    $compatibleBin = Resolve-CompatiblePgBin $serverMajor
    if ($compatibleBin) {
        $pgDump = Join-Path $compatibleBin "pg_dump.exe"
        $pgRestore = Join-Path $compatibleBin "pg_restore.exe"
        Write-Host "Using server-compatible PostgreSQL client tools from: $compatibleBin" -ForegroundColor Yellow
    } else {
        throw "PostgreSQL client/server version mismatch. RDS server is PostgreSQL $serverMajor but pg_dump/pg_restore are newer ($dumpMajor/$restoreMajor). Install PostgreSQL $serverMajor command-line tools or set PG_BIN to PostgreSQL $serverMajor\bin, then rerun. Do not restore a dump produced by a newer major client into an older server."
    }
}

Write-Host "[2/8] Verify target GeoFlow schema state..." -ForegroundColor Cyan
$existingTargetSchemas = & $psql -X -At -h $HostName -p $Port -U $DbUser -d $TargetDb -c "SELECT nspname FROM pg_namespace WHERE nspname IN ('ctr','hr','prj','ops','fin','gis') ORDER BY 1;"
if ($LASTEXITCODE -ne 0) { throw "Could not inspect target schemas." }
$existingTargetSchemas = @($existingTargetSchemas | Where-Object { $_ -and $_.Trim() })
if ($existingTargetSchemas.Count -gt 0) {
    if (-not $ResetPartialTarget) {
        throw "Safety stop: target already contains GeoFlow schemas: $($existingTargetSchemas -join ', '). If this is the known partial restore in a disposable dev/test DB, rerun with -ResetPartialTarget. Otherwise review the target manually."
    }

    Write-Host "ResetPartialTarget was explicitly supplied. Dropping only GeoFlow dev schemas from $TargetDb..." -ForegroundColor Yellow
    foreach ($schema in @('gis','fin','ops','prj','hr','ctr')) {
        if ($existingTargetSchemas -contains $schema) {
            $quotedSchema = Quote-PgIdentifier $schema
            & $psql -X -v ON_ERROR_STOP=1 -h $HostName -p $Port -U $DbUser -d $TargetDb -c "DROP SCHEMA IF EXISTS $quotedSchema CASCADE;"
            if ($LASTEXITCODE -ne 0) { throw "Could not reset partial target schema: $schema" }
        }
    }
}

Write-Host "[3/8] Detect source GeoFlow schemas..." -ForegroundColor Cyan
$sourceSchemas = & $psql -X -At -h $HostName -p $Port -U $DbUser -d $SourceDb -c "SELECT nspname FROM pg_namespace WHERE nspname IN ('ctr','hr','prj','ops','fin') ORDER BY CASE nspname WHEN 'ctr' THEN 1 WHEN 'hr' THEN 2 WHEN 'prj' THEN 3 WHEN 'ops' THEN 4 WHEN 'fin' THEN 5 ELSE 99 END;"
if ($LASTEXITCODE -ne 0) { throw "Could not inspect source schemas." }
$sourceSchemas = @($sourceSchemas | Where-Object { $_ -and $_.Trim() })
foreach ($required in @('ctr','hr','prj','ops')) {
    if ($sourceSchemas -notcontains $required) {
        throw "Required source schema '$required' was not found in $SourceDb."
    }
}
Write-Host "Source schemas: $($sourceSchemas -join ', ')"

Write-Host "[4/8] Mirror required shared extensions from source tenant..." -ForegroundColor Cyan
$extensionAllowList = @('citext','pgcrypto','uuid-ossp','hstore','pg_trgm','btree_gist')
$extensionSql = "SELECT e.extname || '|' || n.nspname FROM pg_extension e JOIN pg_namespace n ON n.oid=e.extnamespace WHERE e.extname IN ('citext','pgcrypto','uuid-ossp','hstore','pg_trgm','btree_gist') ORDER BY e.extname;"
$sourceExtensionRows = & $psql -X -At -h $HostName -p $Port -U $DbUser -d $SourceDb -c $extensionSql
if ($LASTEXITCODE -ne 0) { throw "Could not inspect source extensions." }
$sourceExtensionRows = @($sourceExtensionRows | Where-Object { $_ -and $_.Trim() })

if ($sourceExtensionRows.Count -eq 0) {
    Write-Host "No additional shared extensions detected." -ForegroundColor DarkCyan
} else {
    foreach ($row in $sourceExtensionRows) {
        $parts = $row -split '\|', 2
        if ($parts.Count -ne 2) { throw "Could not parse source extension metadata: $row" }
        $extName = $parts[0].Trim()
        $extSchema = $parts[1].Trim()
        if ($extensionAllowList -notcontains $extName) {
            throw "Unexpected extension outside bootstrap allow-list: $extName"
        }
        if (-not $extSchema) { $extSchema = 'public' }

        $quotedExt = Quote-PgIdentifier $extName
        $quotedExtSchema = Quote-PgIdentifier $extSchema
        if ($extSchema -ne 'public') {
            & $psql -X -v ON_ERROR_STOP=1 -h $HostName -p $Port -U $DbUser -d $TargetDb -c "CREATE SCHEMA IF NOT EXISTS $quotedExtSchema;"
            if ($LASTEXITCODE -ne 0) { throw "Could not create extension schema $extSchema in target." }
        }
        Write-Host "Ensuring extension: $extName (schema=$extSchema)" -ForegroundColor DarkCyan
        & $psql -X -v ON_ERROR_STOP=1 -h $HostName -p $Port -U $DbUser -d $TargetDb -c "CREATE EXTENSION IF NOT EXISTS $quotedExt WITH SCHEMA $quotedExtSchema;"
        if ($LASTEXITCODE -ne 0) { throw "Could not create required extension '$extName' in target." }
    }
}

$tempDump = Join-Path $env:TEMP ("geoflow-schema-{0}.dump" -f ([guid]::NewGuid().ToString('N')))
try {
    Write-Host "[5/8] Schema-only backup from $SourceDb (no business rows)..." -ForegroundColor Cyan
    $dumpArgs = @(
        '-h', $HostName,
        '-p', $Port,
        '-U', $DbUser,
        '-d', $SourceDb,
        '--format=custom',
        '--schema-only',
        '--no-owner',
        '--no-privileges',
        '--file', $tempDump
    )
    foreach ($schema in $sourceSchemas) {
        $dumpArgs += @('--schema', $schema)
    }
    & $pgDump @dumpArgs
    if ($LASTEXITCODE -ne 0) { throw "Schema-only pg_dump failed." }

    Write-Host "[6/8] Restore GeoFlow business schemas into $TargetDb..." -ForegroundColor Cyan
    & $pgRestore -h $HostName -p $Port -U $DbUser -d $TargetDb --no-owner --no-privileges --exit-on-error $tempDump
    if ($LASTEXITCODE -ne 0) { throw "Schema-only pg_restore failed." }

    Write-Host "[7/8] Apply GIS foundation v0.2..." -ForegroundColor Cyan
    & $psql -X -v ON_ERROR_STOP=1 -h $HostName -p $Port -U $DbUser -d $TargetDb -f $foundationSql
    if ($LASTEXITCODE -ne 0) { throw "GIS foundation SQL failed." }

    Write-Host "[8/8] Final verification..." -ForegroundColor Green
    & $psql -X -v ON_ERROR_STOP=1 -h $HostName -p $Port -U $DbUser -d $TargetDb -c "SELECT nspname AS schema_name FROM pg_namespace WHERE nspname IN ('ctr','hr','prj','ops','fin','gis') ORDER BY 1; SELECT table_schema, count(*) AS table_count FROM information_schema.tables WHERE table_schema IN ('ctr','hr','prj','ops','fin','gis') GROUP BY table_schema ORDER BY table_schema; SELECT e.extname, n.nspname AS schema_name FROM pg_extension e JOIN pg_namespace n ON n.oid=e.extnamespace WHERE e.extname IN ('postgis','citext','pgcrypto','uuid-ossp','hstore','pg_trgm','btree_gist') ORDER BY e.extname; SELECT PostGIS_Version();"
    if ($LASTEXITCODE -ne 0) { throw "Final verification failed." }

    Write-Host "GeoFlow development database bootstrap completed successfully." -ForegroundColor Green
    Write-Host "No source business rows were copied; only schema definitions and required shared extensions were restored." -ForegroundColor Green
}
finally {
    if (Test-Path $tempDump) {
        Remove-Item $tempDump -Force
    }
}
