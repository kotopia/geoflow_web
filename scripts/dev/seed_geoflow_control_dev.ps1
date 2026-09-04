param(
    [Parameter(Mandatory = $true)]
    [string]$HostName,

    [string]$Port = "5432",

    [Parameter(Mandatory = $true)]
    [string]$DbUser,

    [string]$TargetDb = "geoflow_control_dev",

    [string]$TestEmail = "gis-dev-admin@geoflow.invalid",

    [string]$TenantDbAlias = "cheonan_db",

    [string]$TenantDbName = "geoflow_dev"
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
if (-not $TestEmail.Contains('@')) { throw "TestEmail must be a valid-looking email address." }

$psql = Resolve-Psql
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$sqlFile = Join-Path $repoRoot "docs\development\geoflow-control-dev-seed.sql"
if (-not (Test-Path $sqlFile)) { throw "Central dev seed SQL not found: $sqlFile" }

$securePassword = Read-Host "Synthetic GeoFlow test login password" -AsSecureString
$bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($securePassword)
$plainPassword = $null
$previousClientEncoding = $env:PGCLIENTENCODING
$previousDevPassword = $env:GEOFLOW_DEV_LOGIN_PASSWORD

try {
    $plainPassword = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr)
    if (-not $plainPassword) { throw "Synthetic login password cannot be empty." }

    $env:GEOFLOW_DEV_LOGIN_PASSWORD = $plainPassword
    $env:PGCLIENTENCODING = "UTF8"

    Write-Host "[1/3] Verify central development schema/catalog..." -ForegroundColor Cyan
    & $psql -X -v ON_ERROR_STOP=1 -h $HostName -p $Port -U $DbUser -d $TargetDb -c "SELECT current_database(); SELECT count(*) AS roles FROM roles; SELECT count(*) AS permissions FROM permissions; SELECT count(*) AS maps_view_bindings FROM roles r JOIN role_permissions rp ON rp.role_id=r.id JOIN permissions p ON p.id=rp.permission_id WHERE r.code='tenant_admin' AND p.code='maps.view';"
    if ($LASTEXITCODE -ne 0) { throw "Central dev seed preflight failed." }

    Write-Host "[2/3] Seed synthetic verified user, group, membership, and static tenant route..." -ForegroundColor Cyan
    & $psql -X -v ON_ERROR_STOP=1 -h $HostName -p $Port -U $DbUser -d $TargetDb `
        -v "test_email=$TestEmail" `
        -v "tenant_db_alias=$TenantDbAlias" `
        -v "tenant_db_name=$TenantDbName" `
        -f $sqlFile
    if ($LASTEXITCODE -ne 0) { throw "Central dev synthetic seed failed." }

    Write-Host "[3/3] Verify login/tenant authorization path..." -ForegroundColor Green
    & $psql -X -v ON_ERROR_STOP=1 -h $HostName -p $Port -U $DbUser -d $TargetDb -c "SELECT u.email, u.is_active, u.email_verified, g.code AS group_code, g.status AS group_status, r.code AS role_code, c.db_alias, c.db_name FROM users u JOIN user_group_map ug ON ug.user_id=u.id JOIN groups g ON g.id=ug.group_id JOIN roles r ON r.id=ug.role_id JOIN group_db_config c ON c.group_id=g.id WHERE u.id='90000000-0000-4000-8000-000000000101'::uuid; SELECT p.code FROM permissions p JOIN role_permissions rp ON rp.permission_id=p.id JOIN roles r ON r.id=rp.role_id WHERE r.code='tenant_admin' AND p.code='maps.view';"
    if ($LASTEXITCODE -ne 0) { throw "Central dev synthetic seed verification failed." }

    Write-Host "GeoFlow central development login seed completed successfully." -ForegroundColor Green
    Write-Host "Login email: $TestEmail" -ForegroundColor Green
    Write-Host "Tenant alias: $TenantDbAlias -> physical DB $TenantDbName" -ForegroundColor Green
    Write-Host "No real tenant DB password was stored in group_db_config; static runtime env remains authoritative." -ForegroundColor Green
}
finally {
    if ($bstr -ne [IntPtr]::Zero) { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr) }
    $plainPassword = $null
    if ($null -eq $previousDevPassword) {
        Remove-Item Env:GEOFLOW_DEV_LOGIN_PASSWORD -ErrorAction SilentlyContinue
    } else {
        $env:GEOFLOW_DEV_LOGIN_PASSWORD = $previousDevPassword
    }
    if ($null -eq $previousClientEncoding) {
        Remove-Item Env:PGCLIENTENCODING -ErrorAction SilentlyContinue
    } else {
        $env:PGCLIENTENCODING = $previousClientEncoding
    }
}
