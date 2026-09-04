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
$venvPython = Join-Path $repoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $sqlFile)) { throw "Central dev seed SQL not found: $sqlFile" }
if (-not (Test-Path $venvPython)) {
    throw "GeoFlow .venv is missing. Run .\scripts\windows\setup_workstation.ps1 -Bootstrap first."
}

$securePassword = Read-Host "Synthetic GeoFlow test login password" -AsSecureString
$bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($securePassword)
$plainPassword = $null
$previousClientEncoding = $env:PGCLIENTENCODING
$previousDevPassword = $env:GEOFLOW_DEV_LOGIN_PASSWORD
$previousDevHash = $env:GEOFLOW_DEV_LOGIN_HASH
$previousStoredHash = $env:GEOFLOW_DEV_LOGIN_STORED_HASH

try {
    $plainPassword = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr)
    if (-not $plainPassword) { throw "Synthetic login password cannot be empty." }

    $env:GEOFLOW_DEV_LOGIN_PASSWORD = $plainPassword
    $env:PGCLIENTENCODING = "UTF8"

    # Generate the synthetic credential with Django's PBKDF2 implementation,
    # matching the algorithm accepted by the live central login verifier.
    $hashOutput = & $venvPython -c "import os; from django.contrib.auth.hashers import PBKDF2PasswordHasher; h=PBKDF2PasswordHasher(); print(h.encode(os.environ['GEOFLOW_DEV_LOGIN_PASSWORD'], h.salt()))"
    if ($LASTEXITCODE -ne 0) { throw "Could not generate Django PBKDF2 password hash." }
    $devLoginHash = (($hashOutput | Select-Object -Last 1) -as [string]).Trim()
    if (-not $devLoginHash.StartsWith("pbkdf2_sha256`$")) {
        throw "Unexpected password hash algorithm generated for synthetic login."
    }
    $env:GEOFLOW_DEV_LOGIN_HASH = $devLoginHash

    Write-Host "[1/4] Verify central development schema/catalog..." -ForegroundColor Cyan
    & $psql -X -v ON_ERROR_STOP=1 -h $HostName -p $Port -U $DbUser -d $TargetDb -c "SELECT current_database(); SELECT count(*) AS roles FROM roles; SELECT count(*) AS permissions FROM permissions; SELECT count(*) AS maps_view_bindings FROM roles r JOIN role_permissions rp ON rp.role_id=r.id JOIN permissions p ON p.id=rp.permission_id WHERE r.code='tenant_admin' AND p.code='maps.view';"
    if ($LASTEXITCODE -ne 0) { throw "Central dev seed preflight failed." }

    Write-Host "[2/4] Seed synthetic verified user, group, membership, and static tenant route..." -ForegroundColor Cyan
    & $psql -X -v ON_ERROR_STOP=1 -h $HostName -p $Port -U $DbUser -d $TargetDb `
        -v "test_email=$TestEmail" `
        -v "tenant_db_alias=$TenantDbAlias" `
        -v "tenant_db_name=$TenantDbName" `
        -f $sqlFile
    if ($LASTEXITCODE -ne 0) { throw "Central dev synthetic seed failed." }

    Write-Host "[3/4] Verify stored password with the same Django PBKDF2 implementation..." -ForegroundColor Cyan
    $storedHashOutput = & $psql -X -At -v ON_ERROR_STOP=1 -h $HostName -p $Port -U $DbUser -d $TargetDb -c "SELECT password_hash FROM users WHERE id='90000000-0000-4000-8000-000000000101'::uuid;"
    if ($LASTEXITCODE -ne 0) { throw "Could not read back synthetic login password hash." }
    $storedHash = (($storedHashOutput | Select-Object -Last 1) -as [string]).Trim()
    if (-not $storedHash) { throw "Synthetic login password hash is empty after seed." }
    $env:GEOFLOW_DEV_LOGIN_STORED_HASH = $storedHash

    & $venvPython -c "import os,sys; from django.contrib.auth.hashers import PBKDF2PasswordHasher; h=PBKDF2PasswordHasher(); encoded=os.environ['GEOFLOW_DEV_LOGIN_STORED_HASH']; ok=h.verify(os.environ['GEOFLOW_DEV_LOGIN_PASSWORD'], encoded); print('password_verifier=' + ('ok' if ok else 'failed') + ' algorithm=pbkdf2_sha256'); sys.exit(0 if ok else 1)"
    if ($LASTEXITCODE -ne 0) {
        throw "Synthetic login password verification failed after writing the hash."
    }

    Write-Host "[4/4] Verify login/tenant authorization path..." -ForegroundColor Green
    & $psql -X -v ON_ERROR_STOP=1 -h $HostName -p $Port -U $DbUser -d $TargetDb -c "SELECT u.email, u.is_active, u.email_verified, g.code AS group_code, g.status AS group_status, r.code AS role_code, c.db_alias, c.db_name FROM users u JOIN user_group_map ug ON ug.user_id=u.id JOIN groups g ON g.id=ug.group_id JOIN roles r ON r.id=ug.role_id JOIN group_db_config c ON c.group_id=g.id WHERE u.id='90000000-0000-4000-8000-000000000101'::uuid; SELECT p.code FROM permissions p JOIN role_permissions rp ON rp.permission_id=p.id JOIN roles r ON r.id=rp.role_id WHERE r.code='tenant_admin' AND p.code='maps.view';"
    if ($LASTEXITCODE -ne 0) { throw "Central dev synthetic seed verification failed." }

    Write-Host "GeoFlow central development login seed completed successfully." -ForegroundColor Green
    Write-Host "Login email: $TestEmail" -ForegroundColor Green
    Write-Host "Password verifier: Django PBKDF2 verified" -ForegroundColor Green
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
    if ($null -eq $previousDevHash) {
        Remove-Item Env:GEOFLOW_DEV_LOGIN_HASH -ErrorAction SilentlyContinue
    } else {
        $env:GEOFLOW_DEV_LOGIN_HASH = $previousDevHash
    }
    if ($null -eq $previousStoredHash) {
        Remove-Item Env:GEOFLOW_DEV_LOGIN_STORED_HASH -ErrorAction SilentlyContinue
    } else {
        $env:GEOFLOW_DEV_LOGIN_STORED_HASH = $previousStoredHash
    }
    if ($null -eq $previousClientEncoding) {
        Remove-Item Env:PGCLIENTENCODING -ErrorAction SilentlyContinue
    } else {
        $env:PGCLIENTENCODING = $previousClientEncoding
    }
}
