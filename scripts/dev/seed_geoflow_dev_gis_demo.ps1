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
    throw "Safety stop: TargetDb must contain 'dev' or 'test'. Current value: $TargetDb"
}

$psql = Resolve-Psql
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$sqlFile = Join-Path $repoRoot "docs\development\gis-dev-demo-seed.sql"
if (-not (Test-Path $sqlFile)) {
    throw "GIS demo seed SQL not found: $sqlFile"
}

$previousClientEncoding = $env:PGCLIENTENCODING
$env:PGCLIENTENCODING = "UTF8"

try {
    Write-Host "[1/3] Verify development target and GIS metadata..." -ForegroundColor Cyan
    & $psql -X -v ON_ERROR_STOP=1 -h $HostName -p $Port -U $DbUser -d $TargetDb -c "SELECT current_database(), PostGIS_Version(); SELECT count(*) AS gis_feature_tables FROM information_schema.tables WHERE table_schema='gis' AND (table_name LIKE 'wtl_%' OR table_name LIKE 'swl_%'); SELECT count(*) AS feature_types FROM gis.meta_feature_type WHERE active; SELECT count(*) AS field_defs FROM gis.meta_field_def;"
    if ($LASTEXITCODE -ne 0) { throw "GIS demo seed preflight failed." }

    Write-Host "[2/3] Seed synthetic tenant chain, project, and representative GIS objects..." -ForegroundColor Cyan
    & $psql -X -v ON_ERROR_STOP=1 -h $HostName -p $Port -U $DbUser -d $TargetDb -f $sqlFile
    if ($LASTEXITCODE -ne 0) { throw "GIS demo seed failed." }

    Write-Host "[3/3] Verify UUID identity/project scope and sample counts..." -ForegroundColor Green
    $verifySql = @"
SELECT c.id AS contract_id, c.code AS contract_code, c.name AS contract_name,
       p.id AS project_id, p.code AS project_code, p.name AS project_name, p.status
FROM ctr.contracts c
JOIN prj.projects p ON p.contract_id = c.id
WHERE c.id='11111111-1111-4111-8111-111111111301'::uuid
ORDER BY p.created_at NULLS LAST, p.id
LIMIT 1;

WITH seed_project AS (
    SELECT id
    FROM prj.projects
    WHERE contract_id='11111111-1111-4111-8111-111111111301'::uuid
    ORDER BY created_at NULLS LAST, id
    LIMIT 1
)
SELECT 'survey' AS layer, count(*) FROM gis.survey WHERE project_id=(SELECT id FROM seed_project)
UNION ALL SELECT 'doro', count(*) FROM gis.doro WHERE project_id=(SELECT id FROM seed_project)
UNION ALL SELECT 'wtl_pipe_lm', count(*) FROM gis.wtl_pipe_lm WHERE project_id=(SELECT id FROM seed_project)
UNION ALL SELECT 'wtl_valv_ps', count(*) FROM gis.wtl_valv_ps WHERE project_id=(SELECT id FROM seed_project)
UNION ALL SELECT 'wtl_manh_ps', count(*) FROM gis.wtl_manh_ps WHERE project_id=(SELECT id FROM seed_project)
UNION ALL SELECT 'swl_pipe_lm', count(*) FROM gis.swl_pipe_lm WHERE project_id=(SELECT id FROM seed_project)
UNION ALL SELECT 'swl_manh_ps', count(*) FROM gis.swl_manh_ps WHERE project_id=(SELECT id FROM seed_project)
ORDER BY layer;

WITH seed_project AS (
    SELECT id
    FROM prj.projects
    WHERE contract_id='11111111-1111-4111-8111-111111111301'::uuid
    ORDER BY created_at NULLS LAST, id
    LIMIT 1
)
SELECT id, ftr_cde, ftr_idn, source_key
FROM gis.wtl_pipe_lm
WHERE project_id=(SELECT id FROM seed_project)
ORDER BY id;

SELECT sl.target_id, ft.standard_name, sl.match_method
FROM gis.survey_link sl
JOIN gis.meta_feature_type ft ON ft.id=sl.feature_type_id
WHERE sl.survey_id='21111111-1111-4111-8111-111111111111'::uuid;
"@
    & $psql -X -v ON_ERROR_STOP=1 -h $HostName -p $Port -U $DbUser -d $TargetDb -c $verifySql
    if ($LASTEXITCODE -ne 0) { throw "GIS demo seed verification failed." }

    Write-Host "Synthetic GIS demo seed completed successfully." -ForegroundColor Green
    Write-Host "All seeded assets use UUID id as authoritative identity; ftr_cde/ftr_idn are NULL by design." -ForegroundColor Green
}
finally {
    if ($null -eq $previousClientEncoding) {
        Remove-Item Env:PGCLIENTENCODING -ErrorAction SilentlyContinue
    } else {
        $env:PGCLIENTENCODING = $previousClientEncoding
    }
}
