param(
    [string]$PythonExe = "",
    [string]$TenantAlias = "cheonan_db",
    [string]$ExpectedCentralDb = "geoflow_control_dev",
    [string]$ExpectedTenantDb = "geoflow_dev"
)

$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
Set-Location $repoRoot

if (-not $PythonExe) {
    $venvPython = Join-Path $repoRoot ".venv\Scripts\python.exe"
    if (-not (Test-Path $venvPython)) {
        throw "GeoFlow .venv is missing. Run .\scripts\windows\setup_workstation.ps1 -Bootstrap first."
    }
    $PythonExe = $venvPython
}

if (-not (Test-Path $PythonExe) -and -not (Get-Command $PythonExe -ErrorAction SilentlyContinue)) {
    throw "Python executable not found: $PythonExe"
}

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

Write-Host "Python runtime: $PythonExe" -ForegroundColor DarkCyan
& $PythonExe -c "import sys; print('python=' + sys.version.split()[0]); import django, openpyxl, psycopg2; print('django=' + django.get_version()); print('openpyxl=' + openpyxl.__version__)"
if ($LASTEXITCODE -ne 0) {
    throw "Pinned Python dependencies are incomplete. Run .\scripts\windows\setup_workstation.ps1 -Bootstrap."
}

Write-Host "[1/4] Verify GeoDjango native libraries..." -ForegroundColor Cyan
& $PythonExe -c "from django.contrib.gis import gdal, geos; print('geodjango_native_libraries=ready')"
if ($LASTEXITCODE -ne 0) {
    throw "GeoDjango native libraries are not loadable. Run .\scripts\windows\set_geodjango_from_qgis.ps1 in this PowerShell session."
}

Write-Host "[2/4] Django configuration check..." -ForegroundColor Cyan
& $PythonExe manage.py check
if ($LASTEXITCODE -ne 0) { throw "python manage.py check failed." }

$verifier = Join-Path $repoRoot "scripts\dev\check_geoflow_dev_runtime.py"
if (-not (Test-Path $verifier)) {
    throw "Runtime verifier not found: $verifier"
}

Write-Host "[3/4] Verify physical DB routing and central login path..." -ForegroundColor Cyan
& $PythonExe $verifier `
    --tenant-alias $TenantAlias `
    --expected-central-db $ExpectedCentralDb `
    --expected-tenant-db $ExpectedTenantDb `
    --mode routing
if ($LASTEXITCODE -ne 0) { throw "Runtime database/login routing verification failed." }

Write-Host "[4/4] Verify GIS metadata, UUID identity, and object counts..." -ForegroundColor Green
& $PythonExe $verifier `
    --tenant-alias $TenantAlias `
    --expected-central-db $ExpectedCentralDb `
    --expected-tenant-db $ExpectedTenantDb `
    --mode gis
if ($LASTEXITCODE -ne 0) { throw "GIS runtime verification failed." }

Write-Host "GeoFlow development runtime preflight completed successfully." -ForegroundColor Green
Write-Host "Central: $ExpectedCentralDb | Tenant alias: $TenantAlias -> $ExpectedTenantDb" -ForegroundColor Green
