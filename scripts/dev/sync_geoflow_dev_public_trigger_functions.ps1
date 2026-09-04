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

if ($SourceDb -eq $TargetDb) {
    throw "SourceDb and TargetDb must be different."
}
if ($TargetDb -notmatch '(?i)(dev|test)') {
    throw "Safety stop: TargetDb must contain 'dev' or 'test'. Current value: $TargetDb"
}

$psql = Resolve-Psql
$schemaLiteralList = "'ctr','hr','prj','ops','fin'"

$query = @"
SELECT pg_get_functiondef(p.oid) || E'\n'
FROM pg_proc p
JOIN pg_namespace pn ON pn.oid = p.pronamespace
WHERE pn.nspname = 'public'
  AND EXISTS (
      SELECT 1
      FROM pg_trigger t
      JOIN pg_class c ON c.oid = t.tgrelid
      JOIN pg_namespace tn ON tn.oid = c.relnamespace
      WHERE t.tgfoid = p.oid
        AND NOT t.tgisinternal
        AND tn.nspname IN ($schemaLiteralList)
  )
ORDER BY p.oid;
"@

Write-Host "Reading public trigger helper function definitions from $SourceDb..." -ForegroundColor Cyan
$functionDefLines = @(& $psql -X -At -v ON_ERROR_STOP=1 -h $HostName -p $Port -U $DbUser -d $SourceDb -c $query)
if ($LASTEXITCODE -ne 0) {
    throw "Could not read public trigger helper functions from source DB."
}

$joined = ($functionDefLines -join [Environment]::NewLine).Trim()
if (-not $joined) {
    Write-Host "No public trigger helper functions are referenced by ctr/hr/prj/ops/fin." -ForegroundColor DarkCyan
    exit 0
}

$tempSql = Join-Path $env:TEMP ("geoflow-public-trigger-functions-{0}.sql" -f ([guid]::NewGuid().ToString('N')))
try {
    $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($tempSql, $joined + [Environment]::NewLine, $utf8NoBom)

    Write-Host "Applying public trigger helper functions to $TargetDb..." -ForegroundColor Cyan
    & $psql -X -v ON_ERROR_STOP=1 -h $HostName -p $Port -U $DbUser -d $TargetDb -f $tempSql
    if ($LASTEXITCODE -ne 0) {
        throw "Could not apply public trigger helper functions to target DB."
    }

    Write-Host "Public trigger helper functions synchronized successfully." -ForegroundColor Green
}
finally {
    if (Test-Path $tempSql) {
        Remove-Item $tempSql -Force
    }
}
