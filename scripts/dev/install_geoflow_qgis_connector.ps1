param(
    [string]$ProfileName = "default",
    [string]$QgisProfilesRoot = ""
)

$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$source = Join-Path $repoRoot "integrations\qgis\geoflow_connector"
if (-not (Test-Path $source)) {
    throw "GeoFlow QGIS connector source not found: $source"
}

if (-not $QgisProfilesRoot) {
    if (-not $env:APPDATA) { throw "APPDATA is unavailable; provide -QgisProfilesRoot explicitly." }
    $QgisProfilesRoot = Join-Path $env:APPDATA "QGIS\QGIS3\profiles"
}

$profileRoot = Join-Path $QgisProfilesRoot $ProfileName
$pluginRoot = Join-Path $profileRoot "python\plugins"
$target = Join-Path $pluginRoot "geoflow_connector"

New-Item -ItemType Directory -Force -Path $pluginRoot | Out-Null

if (Test-Path $target) {
    Remove-Item -Recurse -Force $target
}
Copy-Item -Recurse -Force $source $target

$required = @("metadata.txt", "__init__.py", "plugin.py", "dialog.py", "client.py")
$missing = @($required | Where-Object { -not (Test-Path (Join-Path $target $_)) })
if ($missing.Count -gt 0) {
    throw "QGIS plugin install verification failed. Missing: $($missing -join ', ')"
}

Write-Host "GeoFlow QGIS Connector installed for development." -ForegroundColor Green
Write-Host "Profile: $ProfileName" -ForegroundColor Green
Write-Host "Path:    $target" -ForegroundColor Green
Write-Host "Next: restart QGIS (or reload plugins), then enable Plugins > Manage and Install Plugins > Installed > GeoFlow Connector." -ForegroundColor Cyan
