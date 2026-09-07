param(
    [Parameter(Mandatory = $true)]
    [string]$HostName,

    [string]$Port = "5432",

    [string]$DbUser = "geoflow_admin",

    [string]$CentralDb = "geoflow_control_dev",

    [string]$TenantDb = "geoflow_dev"
)

$ErrorActionPreference = "Stop"

if ($CentralDb -notmatch '(?i)(dev|test)' -or $TenantDb -notmatch '(?i)(dev|test)') {
    throw "Safety stop: CentralDb and TenantDb must both contain dev/test."
}

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$venvPython = Join-Path $repoRoot ".venv\Scripts\python.exe"
$syncScript = Join-Path $repoRoot "scripts\dev\sync_geoflow_dev_gis_catalog_bindings.py"
if (-not (Test-Path $venvPython)) { throw "GeoFlow .venv is missing." }
if (-not (Test-Path $syncScript)) { throw "GIS catalog binding sync script is missing." }

Write-Host "[1/2] Configure isolated development DB environment..." -ForegroundColor Cyan
& (Join-Path $repoRoot "scripts\dev\set_geoflow_dev_runtime_env.ps1") `
    -HostName $HostName `
    -Port $Port `
    -DbUser $DbUser `
    -CentralDb $CentralDb `
    -TenantDb $TenantDb

Write-Host "[2/2] Sync canonical catalog L2 codes to GIS capabilities..." -ForegroundColor Cyan
& $venvPython $syncScript
if ($LASTEXITCODE -ne 0) { throw "GeoFlow GIS catalog binding sync failed." }

Write-Host "GeoFlow real catalog GIS scope binding sync completed successfully." -ForegroundColor Green
