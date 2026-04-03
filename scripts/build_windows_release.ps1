$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path

Push-Location $repoRoot
try {
    $pythonExe = Join-Path $repoRoot ".venv\Scripts\python.exe"
    if (-not (Test-Path $pythonExe)) {
        throw "Could not find virtual environment Python at $pythonExe"
    }

    & $pythonExe -m pip install pyinstaller
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to install or update PyInstaller."
    }

    foreach ($path in @("build", "dist", "releases")) {
        $fullPath = Join-Path $repoRoot $path
        if (Test-Path $fullPath) {
            Remove-Item -Recurse -Force $fullPath
        }
    }

    $specPath = Join-Path $repoRoot "packaging\windows\sd-image-tool.spec"
    if (-not (Test-Path $specPath)) {
        throw "PyInstaller spec file not found: $specPath"
    }

    & $pythonExe -m PyInstaller --clean $specPath
    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller build failed."
    }

    $distRoot = Join-Path $repoRoot "dist\SD Image Tool"
    if (-not (Test-Path $distRoot)) {
        throw "Expected packaged app folder was not created: $distRoot"
    }

    $releaseDir = Join-Path $repoRoot "releases"
    New-Item -ItemType Directory -Force -Path $releaseDir | Out-Null

    $tagVersion = $env:GITHUB_REF_NAME
    if ([string]::IsNullOrWhiteSpace($tagVersion)) {
        $zipName = "SD-Image-Tool-windows-x64.zip"
    }
    else {
        $safeVersion = $tagVersion.Trim()
        $zipName = "SD-Image-Tool-$safeVersion-windows-x64.zip"
    }

    $zipPath = Join-Path $releaseDir $zipName
    Compress-Archive -Path (Join-Path $distRoot "*") -DestinationPath $zipPath -Force

    Write-Host "Created packaged app folder: $distRoot"
    Write-Host "Created release zip: $zipPath"
}
finally {
    Pop-Location
}
