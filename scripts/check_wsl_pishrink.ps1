param(
    [string]$ImagePath = ""
)

$ErrorActionPreference = "Stop"

Set-Location (Join-Path $PSScriptRoot "..")

$code = @'
from sdtool.wsl_shrink import (
    WslPiShrinkConfig,
    build_pishrink_plan,
    check_wsl_pishrink_available,
)
import sys

cfg = WslPiShrinkConfig()
ok = check_wsl_pishrink_available(cfg)

print("Distro:", cfg.distro)
print("PiShrink command:", cfg.pishrink_command)
print("WSL PiShrink available:", "YES" if ok else "NO")

if len(sys.argv) > 1 and sys.argv[1]:
    plan = build_pishrink_plan(sys.argv[1], cfg)
    print("Input image: ", plan.image_path_windows)
    print("Output image:", plan.output_path_windows)
    print("WSL shell command:")
    print(plan.shell_command)

raise SystemExit(0 if ok else 1)
'@

$code | & .\.venv\Scripts\python.exe - $ImagePath