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

$securePassword = Read-Host "RDS development DB password" -AsSecureString
$bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($securePassword)
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
    $env:TENANT_DB_REQUIRE_SECRET_REFERENCES = "False"

    $env:ENABLE_TENANT_PROVISIONING = "0"
    $env:DJANGO_DEBUG = "True"
    $env:DJANGO_ALLOWED_HOSTS = "localhost,127.0.0.1"
    $env:DJANGO_CSRF_TRUSTED_ORIGINS = "http://localhost:8000,http://127.0.0.1:8000"
    $env:DJANGO_CSRF_COOKIE_SECURE = "False"
    $env:DJANGO_SESSION_COOKIE_SECURE = "False"

    $secretBytes = New-Object byte[] 48
    [Security.Cryptography.RandomNumberGenerator]::Fill($secretBytes)
    $env:DJANGO_SECRET_KEY = [Convert]::ToBase64String($secretBytes)

    Write-Host "GeoFlow development runtime environment is set for this PowerShell process." -ForegroundColor Green
    Write-Host "Central: $CentralDb" -ForegroundColor Green
    Write-Host "Tenant alias cheonan_db -> physical DB: $TenantDb" -ForegroundColor Green
    Write-Host "Provisioning disabled; static tenant connection enabled." -ForegroundColor Green
}
finally {
    if ($bstr -ne [IntPtr]::Zero) { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr) }
    $plainPassword = $null
}
