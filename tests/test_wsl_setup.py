from __future__ import annotations

from sdtool.wsl_setup import (
    build_manual_shrink_setup_help,
    build_shrink_setup_confirmation_text,
    build_shrink_setup_script,
    get_shrink_setup_button_label,
)
from sdtool.wsl_shrink import WslAvailabilityReport


def _report(code: str, distro_name: str = "Kali") -> WslAvailabilityReport:
    return WslAvailabilityReport(
        is_ready=(code == "ready"),
        code=code,
        summary=f"summary {code}",
        detail=f"detail {code}",
        help_text=f"help {code}",
        distro_name=distro_name,
    )


def test_missing_pishrink_button_label_uses_actual_distro() -> None:
    assert get_shrink_setup_button_label(_report("missing_pishrink")) == "Install PiShrink in Kali (Step 3 of 3)"


def test_build_shrink_setup_script_stage3_uses_lf_file_runtime_and_mentions_password() -> None:
    script = build_shrink_setup_script(report=_report("missing_pishrink"))

    assert '$Distro = "Kali"' in script
    assert '$linuxScript = ($linuxScript -replace "`r", "").TrimStart("`n")' in script
    assert '[System.IO.File]::WriteAllBytes($linuxScriptPath, $utf8NoBom.GetBytes($linuxScript))' in script
    assert '$wslScriptPath = "/mnt/$driveLetter$tailPath"' in script
    assert 'wsl.exe -d $Distro -- bash "$wslScriptPath"' in script
    assert 'The password will not be shown while you type.' in script
    assert 'bash -lc $bashCommand' not in script
    assert 'wslpath' not in script


def test_manual_help_and_confirmation_use_actual_distro() -> None:
    help_text = build_manual_shrink_setup_help(report=_report("missing_pishrink"))
    confirmation = build_shrink_setup_confirmation_text(_report("missing_pishrink"))

    assert 'Open the Kali WSL distro' in help_text
    assert 'inside the WSL distro Kali' in confirmation
    assert 'password will not be shown while you type' in confirmation
