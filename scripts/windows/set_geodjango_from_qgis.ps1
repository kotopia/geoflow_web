param(
    [string]$QgisRoot = ""
)

$ErrorActionPreference = "Stop"

function Add-PathEntry([string]$PathEntry) {
    if (-not $PathEntry -or -not (Test-Path $PathEntry)) { return }
    $parts = @($env:PATH -split ';')
    if ($parts -notcontains $PathEntry) {
        $env:PATH = "$PathEntry;$env:PATH"
    }
}

function Get-QgisVersion([string]$Name) {
    if (-not $Name) { return [version]'0.0.0' }
    $match = [regex]::Match($Name, '(?i)^QGIS\s+(\d+)(?:\.(\d+))?(?:\.(\d+))?')
    if (-not $match.Success) { return [version]'0.0.0' }
    $major = [int]$match.Groups[1].Value
    $minor = if ($match.Groups[2].Success) { [int]$match.Groups[2].Value } else { 0 }
    $patch = if ($match.Groups[3].Success) { [int]$match.Groups[3].Value } else { 0 }
    return [version]::new($major, $minor, $patch)
}

function Get-QgisBinCandidates([string]$Root) {
    return @(
        (Join-Path $Root 'bin'),
        (Join-Path $Root 'apps\qgis\bin'),
        (Join-Path $Root 'apps\qgis-ltr\bin')
    ) | Where-Object { Test-Path $_ }
}

function Test-QgisRuntime([string]$Root) {
    if (-not $Root -or -not (Test-Path $Root)) { return $false }
    $bins = @(Get-QgisBinCandidates $Root)
    if ($bins.Count -eq 0) { return $false }

    $hasGdal = $false
    $hasGeos = $false
    foreach ($bin in $bins) {
        if (-not $hasGdal) {
            $gdal = Get-ChildItem $bin -File -Filter 'gdal*.dll' -ErrorAction SilentlyContinue |
                Where-Object { $_.Name -match '^gdal\d+\.dll$' } |
                Select-Object -First 1
            $hasGdal = [bool]$gdal
        }
        if (-not $hasGeos) {
            $hasGeos = Test-Path (Join-Path $bin 'geos_c.dll')
        }
        if ($hasGdal -and $hasGeos) { return $true }
    }
    return $false
}

function Find-QgisRuntime {
    $candidates = @()
    $programRoots = @(${env:ProgramFiles}, ${env:ProgramFiles(x86)}) |
        Where-Object { $_ -and (Test-Path $_) } |
        Select-Object -Unique

    foreach ($programRoot in $programRoots) {
        $dirs = @(Get-ChildItem $programRoot -Directory -ErrorAction SilentlyContinue |
            Where-Object { $_.Name -like 'QGIS*' })
        foreach ($dir in $dirs) {
            if (Test-QgisRuntime $dir.FullName) {
                $candidates += [pscustomobject]@{
                    Root = $dir.FullName
                    Name = $dir.Name
                    Version = Get-QgisVersion $dir.Name
                    IsQgis = $dir.Name -match '(?i)^QGIS\s+'
                }
            }
        }
    }

    $osgeo4w = 'C:\OSGeo4W'
    if (Test-QgisRuntime $osgeo4w) {
        $candidates += [pscustomobject]@{
            Root = $osgeo4w
            Name = 'OSGeo4W'
            Version = [version]'0.0.0'
            IsQgis = $false
        }
    }

    if ($candidates.Count -eq 0) { return $null }

    # Prefer a native QGIS installation, then the highest semantic QGIS version.
    # This intentionally supports different workstation patch versions such as
    # QGIS 4.2.1 at home and QGIS 4.2.2 at the office without changing commands.
    return $candidates |
        Sort-Object @{ Expression = { $_.IsQgis }; Descending = $true },
                    @{ Expression = { $_.Version }; Descending = $true },
                    @{ Expression = { $_.Name }; Descending = $true } |
        Select-Object -First 1
}

function Remove-StaleQgisPathEntries {
    $parts = @(
        $env:PATH -split ';' |
            Where-Object {
                $_ -and
                $_ -notmatch '(?i)^C:\\Program Files(?: \(x86\))?\\QGIS [^\\]+\\bin\\?$' -and
                $_ -notmatch '(?i)^C:\\Program Files(?: \(x86\))?\\QGIS [^\\]+\\apps\\qgis(?:-ltr)?\\bin\\?$'
            }
    )
    $env:PATH = $parts -join ';'
}

function Write-VenvQgisBootstrap([string]$BinDir) {
    $repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
    $sitePackages = Join-Path $repoRoot '.venv\Lib\site-packages'
    if (-not (Test-Path $sitePackages)) { return }

    $pthFile = Join-Path $sitePackages 'geoflow_qgis_runtime.pth'
    $escapedBin = $BinDir.Replace('\', '\\').Replace("'", "\'")
    $pthLine = "import os,builtins; p='$escapedBin'; os.environ['PATH']=p+';'+os.environ.get('PATH',''); builtins._geoflow_qgis_dll_dir=os.add_dll_directory(p)"
    Set-Content -Path $pthFile -Value $pthLine -Encoding ASCII
    Write-Host "QGIS venv bootstrap refreshed: $pthFile" -ForegroundColor Yellow
}

$requestedQgisRoot = $QgisRoot
if ($QgisRoot -and -not (Test-QgisRuntime $QgisRoot)) {
    Write-Warning "Requested QGIS runtime is not usable on this workstation: $QgisRoot"
    Write-Warning "GeoFlow will auto-detect another installed QGIS runtime instead."
    $QgisRoot = ""
}

if (-not $QgisRoot) {
    $resolvedRuntime = Find-QgisRuntime
    if ($resolvedRuntime) {
        $QgisRoot = $resolvedRuntime.Root
        Write-Host "Auto-detected QGIS runtime: $QgisRoot" -ForegroundColor Yellow
    }
}

if (-not $QgisRoot -or -not (Test-QgisRuntime $QgisRoot)) {
    $requestedText = if ($requestedQgisRoot) { " Requested root: $requestedQgisRoot." } else { "" }
    throw "QGIS/OSGeo4W runtime with GDAL and GEOS was not found.$requestedText Install QGIS or pass -QgisRoot explicitly."
}

$binCandidates = @(Get-QgisBinCandidates $QgisRoot)

$gdalDll = $null
foreach ($bin in $binCandidates) {
    $candidate = Get-ChildItem $bin -File -Filter 'gdal*.dll' -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -match '^gdal\d+\.dll$' } |
        Sort-Object Name -Descending |
        Select-Object -First 1
    if ($candidate) { $gdalDll = $candidate.FullName; break }
}

$geosDll = $null
foreach ($bin in $binCandidates) {
    $candidate = Join-Path $bin 'geos_c.dll'
    if (Test-Path $candidate) { $geosDll = $candidate; break }
}

if (-not $gdalDll) { throw "GDAL DLL was not found under QGIS root: $QgisRoot" }
if (-not $geosDll) { throw "geos_c.dll was not found under QGIS root: $QgisRoot" }

$runtimeBin = Split-Path $gdalDll -Parent
Remove-StaleQgisPathEntries

$pathCandidates = @(
    $runtimeBin,
    (Join-Path $QgisRoot 'bin'),
    (Join-Path $QgisRoot 'apps\qgis\bin'),
    (Join-Path $QgisRoot 'apps\qgis-ltr\bin'),
    (Join-Path $QgisRoot 'apps\Qt6\bin'),
    (Join-Path $QgisRoot 'apps\Qt5\bin')
)
foreach ($pathEntry in $pathCandidates) { Add-PathEntry $pathEntry }

$env:GDAL_LIBRARY_PATH = $gdalDll
$env:GEOS_LIBRARY_PATH = $geosDll
$env:GEOFLOW_QGIS_ROOT = $QgisRoot
$env:GEOFLOW_QGIS_BIN = $runtimeBin
if (-not $env:DJANGO_SETTINGS_MODULE) {
    $env:DJANGO_SETTINGS_MODULE = 'geoflow_project.settings'
}

# A workstation may have a local-only .pth file created by an older launcher.
# Rewrite it on every start so moving between QGIS 4.2.1 and 4.2.2 never leaves
# Python loading DLLs from the other machine's installation path.
Write-VenvQgisBootstrap $runtimeBin

Write-Host "GeoDjango native library environment configured for this PowerShell session." -ForegroundColor Green
Write-Host "QGIS root: $QgisRoot" -ForegroundColor Green
Write-Host "QGIS runtime bin: $runtimeBin" -ForegroundColor Green
Write-Host "GDAL_LIBRARY_PATH=$gdalDll" -ForegroundColor Green
Write-Host "GEOS_LIBRARY_PATH=$geosDll" -ForegroundColor Green
Write-Host "DJANGO_SETTINGS_MODULE=$env:DJANGO_SETTINGS_MODULE" -ForegroundColor Green
Write-Host "QGIS runtime paths were refreshed for this workstation." -ForegroundColor Green
