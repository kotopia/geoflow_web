param(
    [Parameter(Mandatory = $true)]
    [string]$HostName,

    [string]$Port = "5432",

    [string]$DbUser = "geoflow_admin",

    [string]$CentralDb = "geoflow_control_dev",

    [string]$TenantDb = "geoflow_dev",

    [string]$Listen = "127.0.0.1:8000",

    [string]$QgisRoot = ""
)

$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
Set-Location $repoRoot

$venvPython = Join-Path $repoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    throw "GeoFlow .venv is missing. Run .\scripts\windows\setup_workstation.ps1 -Bootstrap first."
}

if ($CentralDb -notmatch '(?i)(dev|test)' -or $TenantDb -notmatch '(?i)(dev|test)') {
    throw "Safety stop: CentralDb and TenantDb must both contain dev/test."
}

Write-Host "[1/4] Configure isolated development database environment..." -ForegroundColor Cyan
& (Join-Path $repoRoot "scripts\dev\set_geoflow_dev_runtime_env.ps1") `
    -HostName $HostName `
    -Port $Port `
    -DbUser $DbUser `
    -CentralDb $CentralDb `
    -TenantDb $TenantDb

Write-Host "[2/4] Configure GeoDjango native libraries from QGIS..." -ForegroundColor Cyan
$qgisScript = Join-Path $repoRoot "scripts\windows\set_geodjango_from_qgis.ps1"
if ($QgisRoot) {
    & $qgisScript -QgisRoot $QgisRoot
} else {
    & $qgisScript
}

# Hard fail before Django starts if anything drifted away from the isolated DBs.
if ($env:GEOFLOW_DEV_RUNTIME_STRICT -ne "1") {
    throw "Safety stop: strict GeoFlow development runtime guard is not enabled."
}
if ($env:CENTRAL_DB_NAME -ne $CentralDb) {
    throw "Safety stop: CENTRAL_DB_NAME drifted to '$($env:CENTRAL_DB_NAME)'."
}
if ($env:TENANT_DB_NAME -ne $TenantDb) {
    throw "Safety stop: TENANT_DB_NAME drifted to '$($env:TENANT_DB_NAME)'."
}
if ($env:ENABLE_TENANT_PROVISIONING -ne "0") {
    throw "Safety stop: tenant provisioning must remain disabled in GIS development runtime."
}

Write-Host "[3/4] Run read-only development runtime preflight..." -ForegroundColor Cyan
& (Join-Path $repoRoot "scripts\dev\check_geoflow_dev_runtime.ps1") `
    -PythonExe $venvPython `
    -ExpectedCentralDb $CentralDb `
    -ExpectedTenantDb $TenantDb

Write-Host "[4/4] Start isolated GeoFlow development server..." -ForegroundColor Green
Write-Host "STRICT DEV DB GUARD: enabled" -ForegroundColor Green
Write-Host "Central DB: $CentralDb" -ForegroundColor Green
Write-Host "Tenant DB:  $TenantDb" -ForegroundColor Green
Write-Host "Login:      http://$Listen/login/" -ForegroundColor Green
Write-Host "GIS:        http://$Listen/gis/" -ForegroundColor Green
Write-Host "Press Ctrl+C to stop the development server." -ForegroundColor DarkCyan

& $venvPython manage.py runserver $Listen --noreload
if ($LASTEXITCODE -ne 0) { throw "GeoFlow development server exited with an error." }
