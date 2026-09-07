param(
    [string]$Email = "gis-dev-admin@geoflow.invalid",
    [string]$TenantAlias = "cheonan_db",
    [string]$ExpectedCentralDb = "geoflow_control_dev",
    [string]$ExpectedTenantDb = "geoflow_dev"
)

$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
Set-Location $repoRoot

$venvPython = Join-Path $repoRoot ".venv\Scripts\python.exe"
$diagnostic = Join-Path $repoRoot "scripts\dev\diagnose_geoflow_dev_login.py"
if (-not (Test-Path $venvPython)) {
    throw "GeoFlow .venv is missing."
}
if (-not (Test-Path $diagnostic)) {
    throw "Login diagnostic script is missing."
}

if ($env:CENTRAL_DB_NAME -ne $ExpectedCentralDb) {
    throw "Safety stop: CENTRAL_DB_NAME must be $ExpectedCentralDb in this PowerShell session."
}
if ($env:TENANT_DB_NAME -ne $ExpectedTenantDb) {
    throw "Safety stop: TENANT_DB_NAME must be $ExpectedTenantDb in this PowerShell session."
}

$securePassword = Read-Host "Synthetic GeoFlow test login password to verify" -AsSecureString
$bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($securePassword)
$previousPassword = $env:GEOFLOW_DEV_DIAGNOSTIC_PASSWORD
try {
    $plainPassword = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr)
    if (-not $plainPassword) { throw "Diagnostic password cannot be empty." }
    $env:GEOFLOW_DEV_DIAGNOSTIC_PASSWORD = $plainPassword

    Write-Host "Running exact live-login prerequisite diagnostic (read-only)..." -ForegroundColor Cyan
    & $venvPython $diagnostic `
        --email $Email `
        --tenant-alias $TenantAlias `
        --expected-central-db $ExpectedCentralDb `
        --expected-tenant-db $ExpectedTenantDb
    $exitCode = $LASTEXITCODE
    if ($exitCode -ne 0) {
        throw "GeoFlow development login diagnostic failed with code $exitCode."
    }
}
finally {
    if ($bstr -ne [IntPtr]::Zero) { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr) }
    $plainPassword = $null
    if ($null -eq $previousPassword) {
        Remove-Item Env:GEOFLOW_DEV_DIAGNOSTIC_PASSWORD -ErrorAction SilentlyContinue
    } else {
        $env:GEOFLOW_DEV_DIAGNOSTIC_PASSWORD = $previousPassword
    }
}
