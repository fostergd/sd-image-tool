$ErrorActionPreference = "Stop"

Set-Location (Join-Path $PSScriptRoot "..")

if (-not (Test-Path ".venv")) {
    python -m venv .venv
}

& .\.venv\Scripts\python.exe -m pip install --upgrade pip
& .\.venv\Scripts\python.exe -m pip install -e ".[dev]"

Write-Host ""
Write-Host "Bootstrap complete."
Write-Host "Next:"
Write-Host "  .\scripts\run_tests.ps1"
Write-Host "  .\scripts\run_app.ps1"