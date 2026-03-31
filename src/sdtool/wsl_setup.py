from __future__ import annotations

import ctypes
import subprocess
import sys
import tempfile
from pathlib import Path

from sdtool.wsl_shrink import WslAvailabilityReport, WslPiShrinkConfig, get_shrink_availability_report


_PISHRINK_URL = "https://raw.githubusercontent.com/Drewsif/PiShrink/master/pishrink.sh"


def _default_distro_name(config: WslPiShrinkConfig | None = None) -> str:
    cfg = config or WslPiShrinkConfig()
    return cfg.distro or "Ubuntu"


def _resolved_distro_name(report: WslAvailabilityReport | None, config: WslPiShrinkConfig | None = None) -> str:
    if report and report.distro_name:
        return report.distro_name
    return _default_distro_name(config)


def get_shrink_setup_button_label(
    report: WslAvailabilityReport,
    config: WslPiShrinkConfig | None = None,
) -> str:
    distro_name = _resolved_distro_name(report, config)

    if report.code == "missing_wsl":
        return "Install WSL (Step 1 of 3)"
    if report.code == "missing_distro":
        return f"Install {distro_name} Distro (Step 2 of 3)"
    if report.code == "missing_pishrink":
        return f"Install PiShrink in {distro_name} (Step 3 of 3)"
    if report.code == "ready":
        return f"Repair PiShrink in {distro_name}"
    return "Install / Repair Shrink Support"


def build_shrink_setup_confirmation_text(
    report: WslAvailabilityReport,
    config: WslPiShrinkConfig | None = None,
) -> str:
    distro_name = _resolved_distro_name(report, config)

    if report.code == "missing_wsl":
        action = (
            "This will start Step 1 of 3 and install the Windows Subsystem for Linux feature on this PC.\n\n"
            "After this step, reboot if Windows says it is required. Then return to the app, click Re-check Shrink Readiness, "
            f"and continue with Step 2 of 3 to install {distro_name}, followed by Step 3 of 3 to install PiShrink."
        )
    elif report.code == "missing_distro":
        action = (
            f"This will start Step 2 of 3 and install the Linux distro {distro_name}.\n\n"
            f"Windows may open {distro_name} and ask you to create a Linux username and password. After that finishes, type exit if needed, close the Linux shell, "
            "return to the app, click Re-check Shrink Readiness, and continue with Step 3 of 3 to install PiShrink."
        )
    elif report.code == "missing_pishrink":
        action = (
            f"This will start Step 3 of 3 and install PiShrink inside the WSL distro {distro_name}.\n\n"
            "If prompted for your Linux sudo password, type it and press Enter. The password will not be shown while you type.\n\n"
            "When it finishes, return to the app and click Re-check Shrink Readiness."
        )
    elif report.code == "ready":
        action = (
            f"Shrink support already looks ready in {distro_name}. This will rerun the PiShrink install/repair step inside that distro."
        )
    else:
        action = (
            "This will open the shrink setup helper and attempt to install or repair the missing parts of WSL/PiShrink.\n\n"
            "The helper may require a reboot or ask you to launch the Linux distro once before shrink becomes available."
        )

    return (
        f"Current status: {report.summary}\n\n"
        f"Details: {report.detail}\n\n"
        f"{action}\n\n"
        "Continue?"
    )


def _build_common_header(distro_name: str) -> str:
    return f'''$ErrorActionPreference = "Stop"
$Distro = "{distro_name}"

try {{
'''


def _build_common_footer() -> str:
    return '''
}
catch {
    Write-Host ""
    Write-Host "Setup failed:" -ForegroundColor Red
    Write-Host $_.Exception.Message -ForegroundColor Red
}
finally {
    Write-Host ""
    Read-Host "Press Enter to close this window" | Out-Null
    exit
}
'''


def _build_step3_body(cfg: WslPiShrinkConfig, distro_name: str) -> str:
    pishrink_target = f"/usr/local/bin/{cfg.pishrink_command}"
    linux_lines = [
        "set -e",
        'if command -v sudo >/dev/null 2>&1; then SUDO=sudo; else SUDO=; fi',
        '$SUDO apt-get update',
        '$SUDO apt-get install -y curl',
        f'$SUDO curl -fsSL "{_PISHRINK_URL}" -o "{pishrink_target}"',
        f'$SUDO chmod +x "{pishrink_target}"',
        f'command -v {cfg.pishrink_command}',
        '',
    ]
    joined_lines = "\n".join(linux_lines)
    return f'''
    Write-Host "SD Image Tool shrink setup" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "Step 3 of 3: Install PiShrink" -ForegroundColor Yellow
    Write-Host "This step installs PiShrink inside the WSL distro $Distro."
    Write-Host "If prompted for your Linux sudo password, type it and press Enter. The password will not be shown while you type."
    Write-Host ""
    $linuxScript = @'
{joined_lines}'@
    $linuxScript = ($linuxScript -replace "`r", "").TrimStart("`n")
    if (-not $linuxScript.EndsWith("`n")) {{
        $linuxScript += "`n"
    }}
    $linuxScriptPath = Join-Path $env:TEMP "sdtool-install-pishrink.sh"
    $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllBytes($linuxScriptPath, $utf8NoBom.GetBytes($linuxScript))

    $absoluteScriptPath = [System.IO.Path]::GetFullPath($linuxScriptPath)
    $driveLetter = $absoluteScriptPath.Substring(0, 1).ToLowerInvariant()
    $tailPath = $absoluteScriptPath.Substring(2).Replace('\\', '/')
    $wslScriptPath = "/mnt/$driveLetter$tailPath"

    wsl.exe -d $Distro -- bash "$wslScriptPath"
    Write-Host ""
    Write-Host "Step 3 completed. Return to the app and click Re-check Shrink Readiness." -ForegroundColor Green
'''


def build_shrink_setup_script(
    config: WslPiShrinkConfig | None = None,
    report: WslAvailabilityReport | None = None,
) -> str:
    cfg = config or WslPiShrinkConfig()
    info = report or get_shrink_availability_report(cfg)
    distro_name = _resolved_distro_name(info, cfg)

    header = _build_common_header(distro_name)
    footer = _build_common_footer()

    if info.code == "missing_wsl":
        body = '''
    Write-Host "SD Image Tool shrink setup" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "Step 1 of 3: Install WSL" -ForegroundColor Yellow
    Write-Host "This step enables the Windows Subsystem for Linux feature only."
    Write-Host "After this step, reboot if Windows says it is required."
    Write-Host "Then return to the app, click Re-check Shrink Readiness, and continue with Step 2 of 3."
    Write-Host ""
    wsl.exe --install --no-distribution
    Write-Host ""
    Write-Host "Step 1 completed. If Windows requested a reboot, reboot now before continuing." -ForegroundColor Green
    Write-Host "After reboot, run the app again and continue with Step 2 of 3 to install $Distro."
'''
        return header + body + footer

    if info.code == "missing_distro":
        body = '''
    Write-Host "SD Image Tool shrink setup" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "Step 2 of 3: Install Linux distro" -ForegroundColor Yellow
    Write-Host "This step installs the distro $Distro."
    Write-Host "Windows may open the distro and ask you to create a Linux username and password."
    Write-Host "If a Linux shell opens, finish first-run setup, type exit if needed, then close that shell."
    Write-Host "After that first-run setup finishes, return to the app, click Re-check Shrink Readiness, and continue with Step 3 of 3."
    Write-Host ""
    wsl.exe --install -d $Distro
    Write-Host ""
    Write-Host "Step 2 completed. If $Distro opened for first-run setup, finish that setup and then run this helper again for Step 3 of 3." -ForegroundColor Green
'''
        return header + body + footer

    return header + _build_step3_body(cfg, distro_name) + footer


def build_manual_shrink_setup_help(
    config: WslPiShrinkConfig | None = None,
    report: WslAvailabilityReport | None = None,
) -> str:
    cfg = config or WslPiShrinkConfig()
    info = report or get_shrink_availability_report(cfg)
    distro_name = _resolved_distro_name(info, cfg)
    pishrink_target = f"/usr/local/bin/{cfg.pishrink_command}"

    lines = [
        f"Status: {info.summary}",
        "",
        f"Details: {info.detail}",
        "",
        "Manual setup steps:",
    ]

    if info.code == "missing_wsl":
        lines.extend(
            [
                "1. Open PowerShell as Administrator.",
                "2. Run: wsl --install --no-distribution",
                "3. Restart Windows if prompted.",
                "4. Return to the app and click Re-check Shrink Readiness.",
                f"5. Then run: wsl --install -d {distro_name}",
                f"6. Launch {distro_name} once to finish first-run setup, then return to the app for PiShrink installation.",
            ]
        )
    elif info.code == "missing_distro":
        lines.extend(
            [
                "1. Open PowerShell as Administrator.",
                f"2. Run: wsl --install -d {distro_name}",
                f"3. Launch {distro_name} once to finish first-run setup.",
                "4. Return to the app and click Re-check Shrink Readiness.",
            ]
        )
    elif info.code == "missing_pishrink":
        lines.extend(
            [
                f"1. Open the {distro_name} WSL distro.",
                "2. Run these commands:",
                "   sudo apt-get update",
                "   sudo apt-get install -y curl",
                f"   sudo curl -fsSL {_PISHRINK_URL} -o {pishrink_target}",
                f"   sudo chmod +x {pishrink_target}",
                f"   command -v {cfg.pishrink_command}",
                "3. Return to the app and click Re-check Shrink Readiness.",
            ]
        )
    elif info.code == "ready":
        lines.extend(
            [
                "Shrink support is already installed and ready on this machine.",
                "If you want to repair or reinstall it, use the Install / Repair button in the app.",
            ]
        )
    else:
        lines.extend(
            [
                "1. Open PowerShell as Administrator.",
                f"2. Run: wsl --install -d {distro_name}",
                "3. If WSL is already installed, make sure a distro is installed and PiShrink is available.",
                "4. Return to the app and click Re-check Shrink Readiness.",
            ]
        )

    return "\n".join(lines)


def _shell_execute_runas(file_path: str, parameters: str) -> int:
    try:
        shell32 = ctypes.windll.shell32
        rc = shell32.ShellExecuteW(None, "runas", file_path, parameters, None, 1)
        return int(rc)
    except Exception:
        return 0


def is_current_process_elevated() -> bool:
    if sys.platform != "win32":
        return False
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def _launch_powershell_script_current_session(script_path: Path) -> tuple[bool, str]:
    try:
        subprocess.Popen(
            [
                "powershell.exe",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(script_path),
            ],
            creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0),
        )
        return True, (
            "The shrink setup helper was started in a new PowerShell window using the current administrator session.\n\n"
            f"Helper script: {script_path}\n\n"
            "Follow the stage instructions shown in that window. When it finishes, return to the app and click Re-check Shrink Readiness."
        )
    except Exception as exc:
        return False, str(exc)


def _launch_elevated_powershell_script(script_path: Path) -> tuple[bool, str]:
    parameters = f'-ExecutionPolicy Bypass -File "{script_path}"'
    rc = _shell_execute_runas("powershell.exe", parameters)
    if rc <= 32:
        return False, f"ShellExecuteW failed with code {rc}."
    return True, (
        "The shrink setup helper was started in a new elevated PowerShell window.\n\n"
        f"Helper script: {script_path}\n\n"
        "Accept the UAC prompt if Windows shows one. Follow the stage instructions shown in that window, then return to the app and click Re-check Shrink Readiness."
    )


def launch_shrink_setup(
    report: WslAvailabilityReport | None = None,
    config: WslPiShrinkConfig | None = None,
) -> tuple[bool, str]:
    if sys.platform != "win32":
        return False, "Shrink setup helper is currently supported on Windows only."

    cfg = config or WslPiShrinkConfig()
    availability_report = report or get_shrink_availability_report(cfg)
    script_text = build_shrink_setup_script(cfg, availability_report)
    script_path = Path(tempfile.gettempdir()) / "sdtool-enable-shrink.ps1"
    script_path.write_text(script_text, encoding="utf-8")

    if is_current_process_elevated():
        return _launch_powershell_script_current_session(script_path)
    return _launch_elevated_powershell_script(script_path)
