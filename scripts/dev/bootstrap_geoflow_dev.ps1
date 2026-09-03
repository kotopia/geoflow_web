param(
    [Parameter(Mandatory = $true)]
    [string]$HostName,

    [string]$Port = "5432",

    [Parameter(Mandatory = $true)]
    [string]$DbUser,

    [string]$SourceDb = "cheonan_db",

    [string]$TargetDb = "geoflow_dev"
)

$ErrorActionPreference = "Stop"

function Resolve-PgTool([string]$Name) {
    if ($env:PG_BIN) {
        $candidate = Join-Path $env:PG_BIN "$Name.exe"
        if (Test-Path $candidate) { return $candidate }
    }
    $cmd = Get-Command $Name -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    throw "$Name was not found. Put PostgreSQL bin on PATH or set PG_BIN to its bin directory."
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

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$foundationSql = Join-Path $repoRoot "docs\architecture\gis-schema-foundation.sql"
if (-not (Test-Path $foundationSql)) {
    throw "GIS foundation SQL not found: $foundationSql"
}

Write-Host "[1/6] Verify target database and PostGIS..." -ForegroundColor Cyan
& $psql -X -v ON_ERROR_STOP=1 -h $HostName -p $Port -U $DbUser -d $TargetDb -c "SELECT current_database() AS db, PostGIS_Version() AS postgis;"
if ($LASTEXITCODE -ne 0) { throw "Target DB/PostGIS verification failed." }

Write-Host "[2/6] Verify target has no existing GeoFlow business schemas..." -ForegroundColor Cyan
$existingTargetSchemas = & $psql -X -At -h $HostName -p $Port -U $DbUser -d $TargetDb -c "SELECT nspname FROM pg_namespace WHERE nspname IN ('ctr','hr','prj','ops','fin','gis') ORDER BY 1;"
if ($LASTEXITCODE -ne 0) { throw "Could not inspect target schemas." }
$existingTargetSchemas = @($existingTargetSchemas | Where-Object { $_ -and $_.Trim() })
if ($existingTargetSchemas.Count -gt 0) {
    throw "Safety stop: target already contains GeoFlow schemas: $($existingTargetSchemas -join ', '). Use a fresh dev DB or review manually."
}

Write-Host "[3/6] Detect source GeoFlow schemas..." -ForegroundColor Cyan
$sourceSchemas = & $psql -X -At -h $HostName -p $Port -U $DbUser -d $SourceDb -c "SELECT nspname FROM pg_namespace WHERE nspname IN ('ctr','hr','prj','ops','fin') ORDER BY CASE nspname WHEN 'ctr' THEN 1 WHEN 'hr' THEN 2 WHEN 'prj' THEN 3 WHEN 'ops' THEN 4 WHEN 'fin' THEN 5 ELSE 99 END;"
if ($LASTEXITCODE -ne 0) { throw "Could not inspect source schemas." }
$sourceSchemas = @($sourceSchemas | Where-Object { $_ -and $_.Trim() })
foreach ($required in @('ctr','hr','prj','ops')) {
    if ($sourceSchemas -notcontains $required) {
        throw "Required source schema '$required' was not found in $SourceDb."
    }
}
Write-Host "Source schemas: $($sourceSchemas -join ', ')"

$tempDump = Join-Path $env:TEMP ("geoflow-schema-{0}.dump" -f ([guid]::NewGuid().ToString('N')))
try {
    Write-Host "[4/6] Schema-only backup from $SourceDb (no business rows)..." -ForegroundColor Cyan
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

    Write-Host "[5/6] Restore GeoFlow business schemas into $TargetDb..." -ForegroundColor Cyan
    & $pgRestore -h $HostName -p $Port -U $DbUser -d $TargetDb --no-owner --no-privileges --exit-on-error $tempDump
    if ($LASTEXITCODE -ne 0) { throw "Schema-only pg_restore failed." }

    Write-Host "[6/6] Apply GIS foundation v0.2..." -ForegroundColor Cyan
    & $psql -X -v ON_ERROR_STOP=1 -h $HostName -p $Port -U $DbUser -d $TargetDb -f $foundationSql
    if ($LASTEXITCODE -ne 0) { throw "GIS foundation SQL failed." }

    Write-Host "Verification:" -ForegroundColor Green
    & $psql -X -v ON_ERROR_STOP=1 -h $HostName -p $Port -U $DbUser -d $TargetDb -c "SELECT nspname AS schema_name FROM pg_namespace WHERE nspname IN ('ctr','hr','prj','ops','fin','gis') ORDER BY 1; SELECT table_schema, count(*) AS table_count FROM information_schema.tables WHERE table_schema IN ('ctr','hr','prj','ops','fin','gis') GROUP BY table_schema ORDER BY table_schema; SELECT PostGIS_Version();"
    if ($LASTEXITCODE -ne 0) { throw "Final verification failed." }

    Write-Host "GeoFlow development database bootstrap completed successfully." -ForegroundColor Green
    Write-Host "No source business rows were copied; only schema definitions were restored." -ForegroundColor Green
}
finally {
    if (Test-Path $tempDump) {
        Remove-Item $tempDump -Force
    }
}
