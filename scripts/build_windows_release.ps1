$ErrorActionPreference = 'Stop'

$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Split-Path -Parent $scriptRoot
$venvPython = Join-Path $repoRoot '.venv\Scripts\python.exe'
$specFile = Join-Path $repoRoot 'packaging\windows\sd-image-tool.spec'

if (-not (Test-Path $venvPython)) {
    throw "Virtual environment Python was not found at $venvPython"
}

& $venvPython -m pip install pyinstaller
if ($LASTEXITCODE -ne 0) {
    throw 'Could not install or update PyInstaller.'
}

Push-Location $repoRoot
try {
    & $venvPython -m PyInstaller --noconfirm --clean $specFile
    if ($LASTEXITCODE -ne 0) {
        throw 'PyInstaller build failed.'
    }

    Write-Host ''
    Write-Host 'Build completed successfully.' -ForegroundColor Green
    Write-Host 'Executable folder:' -ForegroundColor Green
    Write-Host (Join-Path $repoRoot 'dist\SD Image Tool')
}
finally {
    Pop-Location
}
