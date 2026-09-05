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

if (-not $QgisRoot) {
    $roots = @()
    $programFiles = ${env:ProgramFiles}
    if ($programFiles -and (Test-Path $programFiles)) {
        $qgisDirs = @(Get-ChildItem $programFiles -Directory -ErrorAction SilentlyContinue |
            Where-Object { $_.Name -like 'QGIS*' })

        # GeoFlow's current tested desktop connector/runtime is QGIS 3.x.
        # Prefer the newest installed 3.x build over a newer major QGIS 4.x
        # installation until the 4.x runtime is separately validated.
        $roots += $qgisDirs |
            Where-Object { $_.Name -match '^QGIS\s+3\.' } |
            Sort-Object Name -Descending |
            Select-Object -ExpandProperty FullName
        $roots += $qgisDirs |
            Where-Object { $_.Name -notmatch '^QGIS\s+3\.' } |
            Sort-Object Name -Descending |
            Select-Object -ExpandProperty FullName
    }
    $osgeo4w = 'C:\OSGeo4W'
    if (Test-Path $osgeo4w) { $roots += $osgeo4w }
    $QgisRoot = $roots | Select-Object -First 1
}

if (-not $QgisRoot -or -not (Test-Path $QgisRoot)) {
    throw "QGIS/OSGeo4W installation was not found. Install QGIS or pass -QgisRoot explicitly."
}

$binCandidates = @(
    (Join-Path $QgisRoot 'bin'),
    (Join-Path $QgisRoot 'apps\qgis\bin'),
    (Join-Path $QgisRoot 'apps\qgis-ltr\bin')
) | Where-Object { Test-Path $_ }

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

$pathCandidates = @(
    (Join-Path $QgisRoot 'bin'),
    (Join-Path $QgisRoot 'apps\qgis\bin'),
    (Join-Path $QgisRoot 'apps\qgis-ltr\bin'),
    (Join-Path $QgisRoot 'apps\Qt6\bin'),
    (Join-Path $QgisRoot 'apps\Qt5\bin')
)
foreach ($pathEntry in $pathCandidates) { Add-PathEntry $pathEntry }

$env:GDAL_LIBRARY_PATH = $gdalDll
$env:GEOS_LIBRARY_PATH = $geosDll
if (-not $env:DJANGO_SETTINGS_MODULE) {
    $env:DJANGO_SETTINGS_MODULE = 'geoflow_project.settings'
}

Write-Host "GeoDjango native library environment configured for this PowerShell session." -ForegroundColor Green
Write-Host "QGIS root: $QgisRoot" -ForegroundColor Green
Write-Host "GDAL_LIBRARY_PATH=$gdalDll" -ForegroundColor Green
Write-Host "GEOS_LIBRARY_PATH=$geosDll" -ForegroundColor Green
Write-Host "DJANGO_SETTINGS_MODULE=$env:DJANGO_SETTINGS_MODULE" -ForegroundColor Green
Write-Host "QGIS runtime paths were prepended to PATH where present." -ForegroundColor Green
