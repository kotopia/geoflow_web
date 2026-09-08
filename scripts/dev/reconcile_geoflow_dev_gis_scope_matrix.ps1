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
$python = Join-Path $repoRoot ".venv\Scripts\python.exe"
$script = Join-Path $repoRoot "scripts\dev\reconcile_geoflow_dev_gis_scope_matrix.py"
if (-not (Test-Path $python)) { throw "GeoFlow .venv Python not found: $python" }
if (-not (Test-Path $script)) { throw "GIS scope matrix reconciler not found: $script" }

$securePassword = Read-Host "RDS development DB password" -AsSecureString
$bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($securePassword)
$plainPassword = $null

$previous = @{}
$envNames = @(
    "CENTRAL_DB_NAME", "CENTRAL_DB_USER", "CENTRAL_DB_PASSWORD", "CENTRAL_DB_HOST", "CENTRAL_DB_PORT",
    "TENANT_DB_NAME", "TENANT_DB_USER", "TENANT_DB_PASSWORD", "TENANT_DB_HOST", "TENANT_DB_PORT"
)
foreach ($name in $envNames) {
    $previous[$name] = [Environment]::GetEnvironmentVariable($name, "Process")
}

try {
    $plainPassword = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr)
    if (-not $plainPassword) { throw "DB password cannot be empty." }

    $env:CENTRAL_DB_NAME = $CentralDb
    $env:CENTRAL_DB_USER = $DbUser
    $env:CENTRAL_DB_PASSWORD = $plainPassword
    $env:CENTRAL_DB_HOST = $HostName
    $env:CENTRAL_DB_PORT = $Port

    $env:TENANT_DB_NAME = $TenantDb
    $env:TENANT_DB_USER = $DbUser
    $env:TENANT_DB_PASSWORD = $plainPassword
    $env:TENANT_DB_HOST = $HostName
    $env:TENANT_DB_PORT = $Port

    Write-Host "Reconciling GeoFlow GIS development scopes against the real central catalog..." -ForegroundColor Cyan
    Write-Host "Central: $CentralDb | Tenant: $TenantDb" -ForegroundColor DarkCyan
    & $python $script
    if ($LASTEXITCODE -ne 0) {
        throw "Real-catalog GIS scope matrix reconciliation failed."
    }

    Write-Host "GeoFlow real-catalog GIS scope matrix reconciliation completed successfully." -ForegroundColor Green
}
finally {
    if ($bstr -ne [IntPtr]::Zero) {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
    }
    $plainPassword = $null

    foreach ($name in $envNames) {
        $value = $previous[$name]
        if ($null -eq $value) {
            Remove-Item "Env:$name" -ErrorAction SilentlyContinue
        } else {
            [Environment]::SetEnvironmentVariable($name, $value, "Process")
        }
    }
}
