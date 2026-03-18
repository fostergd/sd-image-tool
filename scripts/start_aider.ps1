param(
    [string]$Model = "ollama_chat/qwen2.5-coder:7b"
)

$ErrorActionPreference = "Stop"

Set-Location (Join-Path $PSScriptRoot "..")

$env:OLLAMA_API_BASE = "http://127.0.0.1:11434"
$testCmd = ".\.venv\Scripts\python.exe -m pytest -q"

& py -3.12 -m aider --model $Model --test-cmd $testCmd --auto-test