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

try {
    Write-Host "GeoFlow central catalog GIS candidate inspection (read-only)" -ForegroundColor Cyan
    & $psql -X -v ON_ERROR_STOP=1 -h $HostName -p $Port -U $DbUser -d $TargetDb -c @"
SELECT 'CATEGORY_NODE' AS kind, n.level, n.id, n.code, n.name, n.geom_hint
  FROM catalog.category_node n
 WHERE n.active
   AND (
        n.name ~* '(지하|상수|하수|도로|측량)'
        OR n.code ~* '(UNDER|WATER|SEWER|ROAD|SURVEY|GIS)'
   )
 ORDER BY n.level, n.ord, n.name;

SELECT 'FACET_OPTION' AS kind, o.id, o.code, o.name, o.default_unit, o.geom_hint, f.code AS facet_code, f.name AS facet_name
  FROM catalog.category_facet_option o
  JOIN catalog.category_facet f ON f.id=o.facet_id
 WHERE o.active AND f.active
   AND (
        o.name ~* '(지하|상수|하수|도로|측량)'
        OR o.code ~* '(UNDER|WATER|SEWER|ROAD|SURVEY|GIS)'
   )
 ORDER BY f.ord, o.ord, o.name;

SELECT p.parent_id, pn.code AS parent_code, pn.name AS parent_name,
       p.child_id, cn.code AS child_code, cn.name AS child_name
  FROM catalog.category_parent p
  JOIN catalog.category_node pn ON pn.id=p.parent_id
  JOIN catalog.category_node cn ON cn.id=p.child_id
 WHERE pn.name ~* '(지하|상수|하수|도로|측량)'
    OR cn.name ~* '(지하|상수|하수|도로|측량)'
    OR pn.code ~* '(UNDER|WATER|SEWER|ROAD|SURVEY|GIS)'
    OR cn.code ~* '(UNDER|WATER|SEWER|ROAD|SURVEY|GIS)'
 ORDER BY pn.level, pn.ord, cn.ord;
"@
    if ($LASTEXITCODE -ne 0) { throw "Central catalog GIS candidate inspection failed." }
}
finally {
    if ($null -eq $previousClientEncoding) {
        Remove-Item Env:PGCLIENTENCODING -ErrorAction SilentlyContinue
    } else {
        $env:PGCLIENTENCODING = $previousClientEncoding
    }
}
