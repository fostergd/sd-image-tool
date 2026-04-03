from __future__ import annotations

import ctypes
import subprocess
import sys
import tempfile
from pathlib import Path

from sdtool.wsl_shrink import WslAvailabilityReport, WslPiShrinkConfig, get_shrink_availability_report, windows_to_wsl_path

_PISHRINK_URL = "https://raw.githubusercontent.com/Drewsif/PiShrink/master/pishrink.sh"
_REQUIRED_APT_PACKAGES = ("curl", "parted", "e2fsprogs", "util-linux", "coreutils", "ca-certificates")


def _default_distro_name(config: WslPiShrinkConfig | None = None) -> str:
    cfg = config or WslPiShrinkConfig()
    return cfg.distro or "Ubuntu"


def _resolved_distro_name(report: WslAvailabilityReport | None, config: WslPiShrinkConfig | None = None) -> str:
    if report and report.distro_name:
        return report.distro_name
    return _default_distro_name(config)


def _stage_title(report: WslAvailabilityReport, config: WslPiShrinkConfig | None = None) -> str:
    distro_name = _resolved_distro_name(report, config)
    if report.code == "missing_wsl":
        return "Step 1 of 3: Install WSL"
    if report.code == "missing_distro":
        return f"Step 2 of 3: Install {distro_name}"
    if report.code == "missing_pishrink":
        return f"Step 3 of 3: Install PiShrink in {distro_name}"
    return f"Repair shrink support in {distro_name}"


def _next_action_text(report: WslAvailabilityReport, config: WslPiShrinkConfig | None = None) -> str:
    distro_name = _resolved_distro_name(report, config)
    if report.code == "missing_wsl":
        return (
            f"After Step 1 finishes, reboot if Windows asks, then return to the app, click Re-check Shrink Readiness, "
            f"and continue with Step 2 for {distro_name}."
        )
    if report.code == "missing_distro":
        return (
            f"After Step 2 finishes, launch {distro_name} once to create the Linux user, type exit if the Linux shell stays open, "
            "then return to the app and continue with Step 3."
        )
    if report.code == "missing_pishrink":
        return (
            "After Step 3 finishes, return to the app and click Re-check Shrink Readiness. "
            "If apt reports repository or GPG problems, fix that distro's package sources and then run Step 3 again."
        )
    return f"This reruns the PiShrink and required-tool setup inside {distro_name}."


def get_shrink_setup_button_label(report: WslAvailabilityReport, config: WslPiShrinkConfig | None = None) -> str:
    distro_name = _resolved_distro_name(report, config)
    if report.code == "missing_wsl":
        return "Start Step 1: Install WSL"
    if report.code == "missing_distro":
        return f"Start Step 2: Install {distro_name}"
    if report.code == "missing_pishrink":
        return f"Start Step 3: Install PiShrink in {distro_name}"
    if report.code == "ready":
        return f"Repair shrink support in {distro_name}"
    return "Install / Repair Shrink Support"


def build_shrink_setup_confirmation_text(report: WslAvailabilityReport, config: WslPiShrinkConfig | None = None) -> str:
    distro_name = _resolved_distro_name(report, config)

    if report.code == "missing_wsl":
        action = "This run only installs the Windows Subsystem for Linux feature. It does not install a distro or PiShrink yet. Reboot Windows after this step before continuing, even if Windows does not explicitly ask."
    elif report.code == "missing_distro":
        action = (
            f"This run installs the Linux distro {distro_name}. Windows may open the distro so you can create a Linux username and password."
        )
    elif report.code == "missing_pishrink":
        action = (
            f"This run installs or repairs PiShrink inside the WSL distro {distro_name} and installs the required Linux tools: {', '.join(_REQUIRED_APT_PACKAGES)}.\n\n"
            "If prompted for your Linux sudo password, type it and press Enter. The password will not be shown while you type."
        )
    else:
        action = f"Shrink support already looks ready in {distro_name}. This reruns the PiShrink and required-tool setup inside that distro."

    return (
        f"Current status:\n{report.summary}\n\n"
        f"Details:\n{report.detail}\n\n"
        f"This step will do:\n{action}\n\n"
        f"What happens next:\n{_next_action_text(report, config)}\n\n"
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
    package_list = " ".join(_REQUIRED_APT_PACKAGES)
    linux_lines = [
        "#!/usr/bin/env bash",
        "set -euo pipefail",
        "if command -v sudo >/dev/null 2>&1; then SUDO=sudo; else SUDO=; fi",
        "$SUDO apt-get update",
        f"$SUDO apt-get install -y {package_list}",
        f"$SUDO curl -fsSL \"{_PISHRINK_URL}\" -o \"{pishrink_target}\"",
        f"$SUDO chmod +x \"{pishrink_target}\"",
        f"command -v {cfg.pishrink_command}",
        "command -v parted",
        "command -v losetup",
        "command -v tune2fs",
        "command -v md5sum",
        "command -v e2fsck",
        "command -v resize2fs",
    ]
    linux_script = "\n".join(linux_lines) + "\n"
    temp_script = Path(tempfile.gettempdir()) / "sdtool-install-pishrink.sh"
    wsl_script = windows_to_wsl_path(str(temp_script))
    return f'''
    Write-Host "SD Image Tool shrink setup" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "Step 3 of 3: Install PiShrink" -ForegroundColor Yellow
    Write-Host "This step installs PiShrink inside the WSL distro $Distro."
    Write-Host "It also installs required tools: {', '.join(_REQUIRED_APT_PACKAGES)}."
    Write-Host "If prompted for your Linux sudo password, type it and press Enter. The password will not be shown while you type."
    Write-Host "If apt reports repository or GPG errors, fix that distro's package sources and then run Step 3 again."
    Write-Host ""
    $linuxScript = @'
{linux_script}'@
    $linuxScript = $linuxScript -replace "`r`n", "`n"
    $linuxScript = $linuxScript.TrimStart("`n")
    $linuxScriptPath = Join-Path $env:TEMP "sdtool-install-pishrink.sh"
    $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($linuxScriptPath, $linuxScript, $utf8NoBom)
    $bashCommand = "chmod +x '{wsl_script}' && '{wsl_script}'"
    wsl.exe -d $Distro -- bash -lc $bashCommand
    Write-Host ""
    Write-Host "Step 3 completed. Return to the app and click Re-check Shrink Readiness." -ForegroundColor Green
'''


def build_shrink_setup_script(config: WslPiShrinkConfig | None = None, report: WslAvailabilityReport | None = None) -> str:
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
    Write-Host "After this step, reboot Windows before continuing. Some systems need the reboot even if Windows does not explicitly ask."
    Write-Host "Then return to the app, click Re-check Shrink Readiness, and continue with Step 2 of 3."
    Write-Host ""
    wsl.exe --install --no-distribution
    Write-Host ""
    Write-Host "Step 1 completed. Reboot Windows now before continuing, even if Windows did not explicitly ask for a reboot." -ForegroundColor Green
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
    Write-Host "If a Linux shell opens, finish first-run setup. If the distro window stays open at a prompt afterward, type exit or close that window manually."
    Write-Host "After that first-run setup finishes, return to the app, click Re-check Shrink Readiness, and continue with Step 3 of 3."
    Write-Host ""
    wsl.exe --install -d $Distro
    Write-Host ""
    Write-Host "Step 2 completed. If $Distro opened for first-run setup, finish that setup. If the window stays open at a prompt afterward, type exit or close it manually, then run this helper again for Step 3 of 3." -ForegroundColor Green
'''
        return header + body + footer

    return header + _build_step3_body(cfg, distro_name) + footer


def build_manual_shrink_setup_help(config: WslPiShrinkConfig | None = None, report: WslAvailabilityReport | None = None) -> str:
    cfg = config or WslPiShrinkConfig()
    info = report or get_shrink_availability_report(cfg)
    distro_name = _resolved_distro_name(info, cfg)
    pishrink_target = f"/usr/local/bin/{cfg.pishrink_command}"
    lines = [f"Status: {info.summary}", "", f"Details: {info.detail}", "", "Manual setup steps:"]
    if info.code == "missing_wsl":
        lines.extend([
            "1. Open PowerShell as Administrator.",
            "2. Run: wsl --install --no-distribution",
            "3. Restart Windows after Step 1, even if Windows does not explicitly prompt for it.",
            "4. Return to the app and click Re-check Shrink Readiness.",
            f"5. Then run: wsl --install -d {distro_name}",
            f"6. Launch {distro_name} once to finish first-run setup, then return to the app for Step 3.",
        ])
    elif info.code == "missing_distro":
        lines.extend([
            "1. Open PowerShell as Administrator.",
            f"2. Run: wsl --install -d {distro_name}",
            f"3. Launch {distro_name} once to finish first-run setup and create the Linux user. If that window stays open at a prompt afterward, type exit or close it manually. If that window stays open at a prompt afterward, type exit or close it manually.",
            "4. Return to the app and click Re-check Shrink Readiness.",
            "5. Continue with Step 3 to install PiShrink and required tools.",
        ])
    else:
        lines.extend([
            f"1. Open the {distro_name} WSL distro.",
            "2. Run these commands:",
            "   sudo apt-get update",
            f"   sudo apt-get install -y {' '.join(_REQUIRED_APT_PACKAGES)}",
            f"   sudo curl -fsSL {_PISHRINK_URL} -o {pishrink_target}",
            f"   sudo chmod +x {pishrink_target}",
            f"   command -v {cfg.pishrink_command}",
            "   command -v parted",
            "   command -v losetup",
            "   command -v tune2fs",
            "   command -v md5sum",
            "   command -v e2fsck",
            "   command -v resize2fs",
            "3. If apt-get update fails with repository or GPG errors, fix that distro's package sources, then rerun these commands.",
            "4. Return to the app and click Re-check Shrink Readiness.",
        ])
    return "\n".join(lines)


def _shell_execute_runas(file_path: str, parameters: str) -> int:
    try:
        rc = ctypes.windll.shell32.ShellExecuteW(None, "runas", file_path, parameters, None, 1)
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


def _build_launch_detail(report: WslAvailabilityReport, script_path: Path, *, elevated: bool) -> str:
    prefix = "using the current administrator session" if elevated else "in a new elevated PowerShell window"
    return (
        f"Started {_stage_title(report).lower()} {prefix}.\n\n"
        f"Helper script: {script_path}\n\n"
        f"{_next_action_text(report)}"
    )


def _launch_powershell_script_current_session(script_path: Path, report: WslAvailabilityReport) -> tuple[bool, str]:
    try:
        subprocess.Popen(["powershell.exe", "-ExecutionPolicy", "Bypass", "-File", str(script_path)], creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0))
        return True, _build_launch_detail(report, script_path, elevated=True)
    except Exception as exc:
        return False, str(exc)


def _launch_elevated_powershell_script(script_path: Path, report: WslAvailabilityReport) -> tuple[bool, str]:
    parameters = f'-ExecutionPolicy Bypass -File "{script_path}"'
    rc = _shell_execute_runas("powershell.exe", parameters)
    if rc <= 32:
        return False, f"ShellExecuteW failed with code {rc}."
    return True, _build_launch_detail(report, script_path, elevated=False)


def launch_shrink_setup(report: WslAvailabilityReport | None = None, config: WslPiShrinkConfig | None = None) -> tuple[bool, str]:
    if sys.platform != "win32":
        return False, "Shrink setup helper is currently supported on Windows only."
    cfg = config or WslPiShrinkConfig()
    availability_report = report or get_shrink_availability_report(cfg)
    script_text = build_shrink_setup_script(cfg, availability_report)
    script_path = Path(tempfile.gettempdir()) / "sdtool-enable-shrink.ps1"
    script_path.write_text(script_text, encoding="utf-8")
    if is_current_process_elevated():
        return _launch_powershell_script_current_session(script_path, availability_report)
    return _launch_elevated_powershell_script(script_path, availability_report)
