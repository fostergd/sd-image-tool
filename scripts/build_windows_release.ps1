\
param(
    [string]$Version = "0.1.1"
)

$ErrorActionPreference = "Stop"

$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = Resolve-Path (Join-Path $scriptRoot "..")
Set-Location $projectRoot

$venvPython = Join-Path $projectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    throw "Virtual environment not found at .venv. Activate or create the project venv first."
}

& $venvPython -m pip install pyinstaller
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller install/update failed."
}

$distDir = Join-Path $projectRoot "dist"
$buildDir = Join-Path $projectRoot "build"
$releaseDir = Join-Path $projectRoot "releases"

if (Test-Path $distDir) { Remove-Item $distDir -Recurse -Force }
if (Test-Path $buildDir) { Remove-Item $buildDir -Recurse -Force }
New-Item -ItemType Directory -Force -Path $releaseDir | Out-Null

$env:SDTOOL_VERSION = $Version

$specPath = Join-Path $projectRoot "packaging\windows\sd-image-tool.spec"
& $venvPython -m PyInstaller --clean $specPath
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller build failed."
}

$appFolder = Join-Path $distDir "SD Image Tool"
if (-not (Test-Path $appFolder)) {
    throw "Expected packaged app folder was not created: $appFolder"
}

$zipName = "SD-Image-Tool-v{0}-windows-x64.zip" -f $Version
$zipPath = Join-Path $releaseDir $zipName
if (Test-Path $zipPath) { Remove-Item $zipPath -Force }

Compress-Archive -Path (Join-Path $appFolder "*") -DestinationPath $zipPath -CompressionLevel Optimal

Write-Host ""
Write-Host "Build complete." -ForegroundColor Green
Write-Host "App folder: $appFolder"
Write-Host "Release zip: $zipPath"
