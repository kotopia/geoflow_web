param(
    [Parameter(Mandatory = $true)]
    [string]$HostName,

    [string]$Port = "5432",

    [string]$DbUser = "geoflow_admin",

    [string]$CentralDb = "geoflow_control_dev",

    [string]$TenantDb = "geoflow_dev",

    [string]$Listen = "127.0.0.1:8000",

    [string]$LanHost = "",

    [string]$QgisRoot = ""
)

$ErrorActionPreference = "Stop"

function Resolve-AutoLanHost {
    try {
        $routes = @(Get-NetRoute -AddressFamily IPv4 -DestinationPrefix '0.0.0.0/0' -ErrorAction Stop |
            Where-Object { $_.State -eq 'Alive' -and $_.NextHop -ne '0.0.0.0' } |
            Sort-Object RouteMetric, InterfaceMetric)
        foreach ($route in $routes) {
            $addresses = @(Get-NetIPAddress -AddressFamily IPv4 -InterfaceIndex $route.InterfaceIndex -ErrorAction SilentlyContinue |
                Where-Object {
                    $_.IPAddress -and
                    $_.IPAddress -notmatch '^127\.' -and
                    $_.IPAddress -notmatch '^169\.254\.'
                } |
                Sort-Object SkipAsSource)
            if ($addresses.Count -gt 0) {
                return [string]$addresses[0].IPAddress
            }
        }
    }
    catch {
        # Fall through to the broader interface scan below.
    }

    try {
        $fallback = @(Get-NetIPAddress -AddressFamily IPv4 -ErrorAction Stop |
            Where-Object {
                $_.IPAddress -and
                $_.IPAddress -notmatch '^127\.' -and
                $_.IPAddress -notmatch '^169\.254\.' -and
                $_.AddressState -eq 'Preferred'
            } |
            Sort-Object InterfaceMetric, SkipAsSource |
            Select-Object -First 1)
        if ($fallback.Count -gt 0) {
            return [string]$fallback[0].IPAddress
        }
    }
    catch {}

    return ""
}

function Test-GeoFlowPythonDependencies {
    param([string]$PythonExe)

    & $PythonExe -c "import channels,daphne,django,openpyxl,psycopg2; print('python_dependencies=ready')" 2>$null
    return ($LASTEXITCODE -eq 0)
}

function Ensure-GeoFlowPythonDependencies {
    param(
        [string]$PythonExe,
        [string]$RepoRoot
    )

    $requirementsPath = Join-Path $RepoRoot "requirements.txt"
    if (-not (Test-Path $requirementsPath)) {
        throw "requirements.txt is missing: $requirementsPath"
    }

    $requirementsHash = (Get-FileHash $requirementsPath -Algorithm SHA256).Hash.ToLowerInvariant()
    $stampPath = Join-Path $RepoRoot ".venv\.geoflow_requirements.sha256"
    $installedHash = ""
    if (Test-Path $stampPath) {
        $installedHash = (Get-Content $stampPath -Raw -ErrorAction SilentlyContinue).Trim().ToLowerInvariant()
    }

    $importsReady = Test-GeoFlowPythonDependencies -PythonExe $PythonExe
    $needsSync = (-not $importsReady) -or ($installedHash -ne $requirementsHash)

    if (-not $needsSync) {
        Write-Host "Python dependencies: up to date" -ForegroundColor Green
        return
    }

    if (-not $importsReady) {
        Write-Warning "GeoFlow Python dependencies are incomplete in this workstation .venv."
    } else {
        Write-Host "requirements.txt changed since this .venv was last synchronized." -ForegroundColor Yellow
    }

    Write-Host "Synchronizing .venv from requirements.txt..." -ForegroundColor Yellow
    & $PythonExe -m pip install -r $requirementsPath
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to synchronize GeoFlow .venv from requirements.txt. Check Internet/package index access and retry."
    }

    & $PythonExe -m pip check
    if ($LASTEXITCODE -ne 0) {
        throw "GeoFlow .venv dependency check failed after requirements synchronization."
    }

    if (-not (Test-GeoFlowPythonDependencies -PythonExe $PythonExe)) {
        throw "GeoFlow required Python modules are still unavailable after requirements synchronization."
    }

    Set-Content -Path $stampPath -Value $requirementsHash -Encoding ASCII
    Write-Host "Python dependency synchronization complete." -ForegroundColor Green
}

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
Set-Location $repoRoot

$venvPython = Join-Path $repoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    throw "GeoFlow .venv is missing. Run .\scripts\windows\setup_workstation.ps1 -Bootstrap first."
}

if ($CentralDb -notmatch '(?i)(dev|test)' -or $TenantDb -notmatch '(?i)(dev|test)') {
    throw "Safety stop: CentralDb and TenantDb must both contain dev/test."
}

if ($LanHost -and $LanHost.Trim().ToLowerInvariant() -eq 'auto') {
    $LanHost = Resolve-AutoLanHost
    if (-not $LanHost) {
        throw "LanHost auto-detection failed. Pass the workstation IPv4 explicitly, for example -LanHost 192.168.1.20."
    }
    Write-Host "Auto-detected LAN IPv4: $LanHost" -ForegroundColor Yellow
}

if ($LanHost) {
    try {
        $lanAddress = [System.Net.IPAddress]::Parse($LanHost)
    }
    catch {
        throw "LanHost must be 'auto' or a literal IP address, for example 192.168.219.128."
    }
    if ($lanAddress.AddressFamily -ne [System.Net.Sockets.AddressFamily]::InterNetwork) {
        throw "LanHost currently supports IPv4 only."
    }
    if ([System.Net.IPAddress]::IsLoopback($lanAddress)) {
        throw "LanHost must be the workstation LAN IPv4 address, not loopback."
    }
    if ($Listen -eq "127.0.0.1:8000") {
        $Listen = "0.0.0.0:8000"
    }
}

$listenParts = $Listen -split ':', 2
if ($listenParts.Count -ne 2 -or -not $listenParts[0] -or -not $listenParts[1]) {
    throw "Listen must use host:port form, for example 127.0.0.1:8000."
}
$listenHost = $listenParts[0]
$listenPort = $listenParts[1]

Write-Host "[1/5] Configure isolated development database environment..." -ForegroundColor Cyan
& (Join-Path $repoRoot "scripts\dev\set_geoflow_dev_runtime_env.ps1") `
    -HostName $HostName `
    -Port $Port `
    -DbUser $DbUser `
    -CentralDb $CentralDb `
    -TenantDb $TenantDb

if ($LanHost) {
    $env:DJANGO_ALLOWED_HOSTS = "localhost,127.0.0.1,$LanHost"
    $env:DJANGO_CSRF_TRUSTED_ORIGINS = "http://localhost:$listenPort,http://127.0.0.1:$listenPort,http://$($LanHost):$listenPort"
    Write-Host "LAN QField DEV access: enabled for $LanHost only" -ForegroundColor Yellow
}

Write-Host "[2/5] Configure GeoDjango native libraries from QGIS..." -ForegroundColor Cyan
$qgisScript = Join-Path $repoRoot "scripts\windows\set_geodjango_from_qgis.ps1"
if ($QgisRoot) {
    & $qgisScript -QgisRoot $QgisRoot
} else {
    & $qgisScript
}

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

# Safe development-only login tracing. No password/hash values are logged.
$env:GEOFLOW_DEV_AUTH_DIAGNOSTICS = "1"

Write-Host "[3/5] Synchronize workstation Python dependencies if needed..." -ForegroundColor Cyan
Ensure-GeoFlowPythonDependencies -PythonExe $venvPython -RepoRoot $repoRoot

Write-Host "[4/5] Run read-only development runtime preflight..." -ForegroundColor Cyan
& (Join-Path $repoRoot "scripts\dev\check_geoflow_dev_runtime.ps1") `
    -PythonExe $venvPython `
    -ExpectedCentralDb $CentralDb `
    -ExpectedTenantDb $TenantDb

$daphneExe = Join-Path $repoRoot ".venv\Scripts\daphne.exe"
if (-not (Test-Path $daphneExe)) {
    throw "Daphne is missing from the GeoFlow .venv after requirements synchronization."
}

Write-Host "[5/5] Start isolated GeoFlow ASGI development server..." -ForegroundColor Green
Write-Host "STRICT DEV DB GUARD: enabled" -ForegroundColor Green
Write-Host "DEV AUTH DIAGNOSTICS: enabled (stage/length only; no secrets)" -ForegroundColor Green
Write-Host "GIS REALTIME: WebSocket enabled with one-process in-memory channel layer" -ForegroundColor Green
Write-Host "Central DB: $CentralDb" -ForegroundColor Green
Write-Host "Tenant DB:  $TenantDb" -ForegroundColor Green
Write-Host "QGIS root:  $env:GEOFLOW_QGIS_ROOT" -ForegroundColor Green
Write-Host "Login:      http://$Listen/login/" -ForegroundColor Green
Write-Host "GIS:        http://$Listen/gis/" -ForegroundColor Green
if ($LanHost) {
    Write-Host "LAN Login:  http://$($LanHost):$listenPort/login/" -ForegroundColor Green
    Write-Host "LAN GIS:    http://$($LanHost):$listenPort/gis/" -ForegroundColor Green
    Write-Host "If another device still cannot connect, allow inbound TCP $listenPort on the Windows Private firewall profile." -ForegroundColor Yellow
}
Write-Host "Press Ctrl+C to stop the development server." -ForegroundColor DarkCyan

& $daphneExe -b $listenHost -p $listenPort geoflow_project.asgi:application
if ($LASTEXITCODE -ne 0) { throw "GeoFlow ASGI development server exited with an error." }
