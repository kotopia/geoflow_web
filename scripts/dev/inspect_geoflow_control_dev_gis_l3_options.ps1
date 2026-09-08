param(
    [Parameter(Mandatory = $true)]
    [string]$HostName,

    [string]$Port = "5432",

    [Parameter(Mandatory = $true)]
    [string]$DbUser,

    [string]$TargetDb = "geoflow_control_dev"
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
$previousClientEncoding = $env:PGCLIENTENCODING
$env:PGCLIENTENCODING = "UTF8"
$tempSql = Join-Path $env:TEMP ("geoflow-gis-l3-inspect-{0}.sql" -f ([guid]::NewGuid().ToString('N')))

try {
    $sql = @'
\encoding UTF8
SELECT
    l2.code AS l2_code,
    l2.id AS l2_id,
    s.level_no,
    f.code AS facet_code,
    o.id AS option_id,
    o.code AS option_code,
    COALESCE(o.default_unit,'') AS default_unit,
    COALESCE(o.geom_hint,'') AS geom_hint,
    o.ord AS option_ord
FROM catalog.category_option_set s
JOIN catalog.category_node l2 ON l2.id=s.l2_id
JOIN catalog.category_facet f ON f.id=s.facet_id
JOIN catalog.category_facet_option o ON o.facet_id=f.id
WHERE l2.active=true
  AND f.active=true
  AND o.active=true
  AND l2.code IN ('WATER','SEWERAGE','ROAD')
  AND s.level_no IN (3,4)
ORDER BY l2.code, s.level_no, s.ord, f.ord, o.ord, o.code;
'@
    $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($tempSql, $sql, $utf8NoBom)

    Write-Host "GeoFlow GIS domain L3/L4 option inspection (read-only)" -ForegroundColor Cyan
    & $psql -X -v ON_ERROR_STOP=1 -h $HostName -p $Port -U $DbUser -d $TargetDb -f $tempSql
    if ($LASTEXITCODE -ne 0) { throw "GIS domain L3/L4 option inspection failed." }
}
finally {
    if (Test-Path $tempSql) { Remove-Item $tempSql -Force }
    if ($null -eq $previousClientEncoding) {
        Remove-Item Env:PGCLIENTENCODING -ErrorAction SilentlyContinue
    } else {
        $env:PGCLIENTENCODING = $previousClientEncoding
    }
}
