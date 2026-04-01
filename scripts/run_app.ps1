$ErrorActionPreference = 'Stop'

$repoRoot = Split-Path -Parent $PSScriptRoot
$venvPython = Join-Path $repoRoot '.venv\Scripts\python.exe'

if (Test-Path $venvPython) {
    & $venvPython -m sdtool.app
    exit $LASTEXITCODE
}

py -3.12 -m sdtool.app
exit $LASTEXITCODE
