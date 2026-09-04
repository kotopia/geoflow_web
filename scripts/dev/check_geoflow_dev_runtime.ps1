param(
    [string]$PythonExe = "python",
    [string]$TenantAlias = "cheonan_db",
    [string]$ExpectedCentralDb = "geoflow_control_dev",
    [string]$ExpectedTenantDb = "geoflow_dev"
)

$ErrorActionPreference = "Stop"

$requiredEnv = @(
    'DJANGO_SECRET_KEY',
    'CENTRAL_DB_NAME', 'CENTRAL_DB_USER', 'CENTRAL_DB_PASSWORD', 'CENTRAL_DB_HOST', 'CENTRAL_DB_PORT',
    'TENANT_DB_NAME', 'TENANT_DB_USER', 'TENANT_DB_PASSWORD', 'TENANT_DB_HOST', 'TENANT_DB_PORT'
)
$missing = @($requiredEnv | Where-Object { -not (Get-Item "Env:$_" -ErrorAction SilentlyContinue).Value })
if ($missing.Count -gt 0) {
    throw "Missing required runtime environment variables: $($missing -join ', ')"
}

if ($env:CENTRAL_DB_NAME -ne $ExpectedCentralDb) {
    throw "Safety stop: CENTRAL_DB_NAME is '$($env:CENTRAL_DB_NAME)', expected '$ExpectedCentralDb'."
}
if ($env:TENANT_DB_NAME -ne $ExpectedTenantDb) {
    throw "Safety stop: TENANT_DB_NAME is '$($env:TENANT_DB_NAME)', expected '$ExpectedTenantDb'."
}
if ($ExpectedCentralDb -notmatch '(?i)(dev|test)' -or $ExpectedTenantDb -notmatch '(?i)(dev|test)') {
    throw "Safety stop: expected central/tenant DB names must be dev/test databases."
}

Write-Host "[1/3] Django configuration check..." -ForegroundColor Cyan
& $PythonExe manage.py check
if ($LASTEXITCODE -ne 0) { throw "python manage.py check failed." }

Write-Host "[2/3] Verify physical database routing..." -ForegroundColor Cyan
$routeCode = @"
from django.db import connections
central = connections['default']
tenant = connections['$TenantAlias']
with central.cursor() as c:
    c.execute('select current_database()')
    central_db = c.fetchone()[0]
with tenant.cursor() as c:
    c.execute('select current_database(), PostGIS_Version()')
    tenant_db, postgis = c.fetchone()
print(f'central_db={central_db}')
print(f'tenant_alias=$TenantAlias tenant_db={tenant_db}')
print(f'postgis={postgis}')
if central_db != '$ExpectedCentralDb':
    raise SystemExit(f'central DB mismatch: {central_db}')
if tenant_db != '$ExpectedTenantDb':
    raise SystemExit(f'tenant DB mismatch: {tenant_db}')
"@
& $PythonExe manage.py shell -c $routeCode
if ($LASTEXITCODE -ne 0) { throw "Runtime database routing verification failed." }

Write-Host "[3/3] Verify GIS metadata, synthetic project, and object counts..." -ForegroundColor Green
$gisCode = @"
from django.db import connections
conn = connections['$TenantAlias']
with conn.cursor() as c:
    c.execute("select count(*) from gis.meta_feature_type where active")
    feature_types = c.fetchone()[0]
    c.execute("select count(*) from gis.meta_field_def")
    field_defs = c.fetchone()[0]
    c.execute("select id::text, code, name from prj.projects where code='GIS-DEV-001' order by updated_at desc nulls last limit 1")
    project = c.fetchone()
    if not project:
        raise SystemExit('synthetic GIS project not found')
    project_id = project[0]
    c.execute("select count(*) from gis.wtl_pipe_lm where project_id=%s", [project_id])
    wtl_pipe = c.fetchone()[0]
    c.execute("select count(*) from gis.wtl_valv_ps where project_id=%s", [project_id])
    wtl_valv = c.fetchone()[0]
    c.execute("select count(*) from gis.swl_pipe_lm where project_id=%s", [project_id])
    swl_pipe = c.fetchone()[0]
    c.execute("select count(*) from gis.survey where project_id=%s", [project_id])
    survey = c.fetchone()[0]
print(f'feature_types={feature_types} field_defs={field_defs}')
print(f'project_id={project_id} code={project[1]} name={project[2]}')
print(f'counts survey={survey} wtl_pipe_lm={wtl_pipe} wtl_valv_ps={wtl_valv} swl_pipe_lm={swl_pipe}')
if feature_types != 19:
    raise SystemExit(f'expected 19 feature types, got {feature_types}')
if field_defs <= 0:
    raise SystemExit('field metadata is empty')
"@
& $PythonExe manage.py shell -c $gisCode
if ($LASTEXITCODE -ne 0) { throw "GIS runtime verification failed." }

Write-Host "GeoFlow development runtime preflight completed successfully." -ForegroundColor Green
Write-Host "Central: $ExpectedCentralDb | Tenant alias: $TenantAlias -> $ExpectedTenantDb" -ForegroundColor Green
