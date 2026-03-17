$ErrorActionPreference = "Stop"

Set-Location (Join-Path $PSScriptRoot "..")

$recreateVenv = $false

if (Test-Path ".venv\Scripts\python.exe") {
    $venvVersion = & .\.venv\Scripts\python.exe -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
    if ($venvVersion -ne "3.12") {
        Write-Host "Existing .venv uses Python $venvVersion. Recreating with Python 3.12..."
        Remove-Item -Recurse -Force .venv
        $recreateVenv = $true
    }
}
else {
    $recreateVenv = $true
}

if ($recreateVenv) {
    & py -3.12 -m venv .venv
}

& .\.venv\Scripts\python.exe -m pip install --upgrade pip
& .\.venv\Scripts\python.exe -m pip install -e ".[dev]"

Write-Host ""
Write-Host "Bootstrap complete."
Write-Host "Next:"
Write-Host "  .\scripts\run_tests.ps1"
Write-Host "  .\scripts\run_app.ps1"