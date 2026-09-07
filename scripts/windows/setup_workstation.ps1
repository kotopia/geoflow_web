param(
    [switch]$Bootstrap,
    [switch]$Validate
)

$ErrorActionPreference = "Stop"

function Write-Check {
    param([string]$Label, [string]$Value)
    Write-Host ("{0}={1}" -f $Label, $Value)
}

function Require-Command {
    param([string]$Name)
    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "Required command is unavailable: $Name"
    }
}

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
Set-Location $RepoRoot

if (-not (Test-Path (Join-Path $RepoRoot "manage.py"))) {
    throw "Repository root validation failed: manage.py not found"
}
if (-not (Test-Path (Join-Path $RepoRoot "AGENTS.md"))) {
    throw "Repository root validation failed: AGENTS.md not found"
}

Require-Command git
Write-Check "repo_root" $RepoRoot
Write-Check "git_version" ((git --version) -replace '^git version\s+', '')

$Branch = (git rev-parse --abbrev-ref HEAD).Trim()
Write-Check "git_branch" $Branch
if ($Branch -ne "release/stabilized-deploy") {
    Write-Warning "Expected release/stabilized-deploy; current branch is $Branch"
}

$PythonLauncher = $null
if (Get-Command py -ErrorAction SilentlyContinue) {
    try {
        $Version = (& py -3.12 -c "import sys; print('.'.join(map(str, sys.version_info[:3])))" 2>$null).Trim()
        if ($LASTEXITCODE -eq 0) {
            $PythonLauncher = @("py", "-3.12")
        }
    } catch {
        $PythonLauncher = $null
    }
}

if (-not $PythonLauncher -and (Get-Command python -ErrorAction SilentlyContinue)) {
    $Version = (& python -c "import sys; print('.'.join(map(str, sys.version_info[:3])))").Trim()
    if ($Version -match '^3\.12\.') {
        $PythonLauncher = @("python")
    }
}

if (-not $PythonLauncher) {
    throw "Python 3.12 was not found. Install 64-bit Python 3.12 and run this script again."
}
Write-Check "python_version" $Version

$VenvDir = Join-Path $RepoRoot ".venv"
$VenvPython = Join-Path $VenvDir "Scripts\python.exe"

if ($Bootstrap) {
    if (-not (Test-Path $VenvPython)) {
        Write-Host "Creating .venv..."
        if ($PythonLauncher.Count -eq 2) {
            & $PythonLauncher[0] $PythonLauncher[1] -m venv .venv
        } else {
            & $PythonLauncher[0] -m venv .venv
        }
    }

    Write-Host "Installing pinned Python dependencies..."
    & $VenvPython -m pip install --upgrade pip
    & $VenvPython -m pip install -r requirements.txt
    & $VenvPython -m pip check
}

if (Test-Path $VenvPython) {
    $DjangoVersion = (& $VenvPython -c "import django; print(django.get_version())" 2>$null).Trim()
    if ($LASTEXITCODE -eq 0) {
        Write-Check "django_version" $DjangoVersion
    } else {
        Write-Warning "Django is not available in .venv; run with -Bootstrap"
    }

    if (-not $env:DJANGO_SETTINGS_MODULE) {
        $env:DJANGO_SETTINGS_MODULE = "geoflow_project.settings"
    }
    try {
        & $VenvPython -c "import django; django.setup(); from django.contrib.gis import gdal, geos; print('geodjango_native_libraries=ready'); print('gdal_version=' + '.'.join(map(str, gdal.GDAL_VERSION)))"
        if ($LASTEXITCODE -ne 0) { throw "GeoDjango import failed" }
    } catch {
        Write-Check "geodjango_native_libraries" "attention_required"
        Write-Warning "Windows GDAL/GEOS runtime is not yet loadable. Configure the native GIS libraries before local GeoDjango work."
    }
} else {
    Write-Check "venv" "missing"
    Write-Warning "Run this script with -Bootstrap to create .venv."
}

$EnvPath = Join-Path $RepoRoot ".env"
if (Test-Path $EnvPath) {
    Write-Check "dotenv" "present"
} else {
    Write-Check "dotenv" "missing"
    Write-Warning ".env is intentionally not stored in Git. Transfer or recreate it securely on this workstation."
}

if ($Validate) {
    if (-not (Test-Path $VenvPython)) {
        throw "Cannot validate without .venv. Run with -Bootstrap first."
    }
    if (-not (Test-Path $EnvPath)) {
        throw "Cannot run Django validation because .env is missing. The script will not create or print it."
    }

    Write-Host "Running local Django configuration checks (no migrate)..."
    & $VenvPython manage.py check
    & $VenvPython manage.py check_release_preflight --strict
}

$Status = git status --short
if ([string]::IsNullOrWhiteSpace(($Status -join ""))) {
    Write-Check "git_worktree" "clean"
} else {
    Write-Check "git_worktree" "has_changes"
    git status --short
}

Write-Host "Workstation check complete. No migration, DB write, S3 mutation, SMTP delivery, or deployment command was run."
