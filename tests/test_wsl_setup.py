from __future__ import annotations

from sdtool.wsl_setup import (
    build_manual_shrink_setup_help,
    build_shrink_setup_confirmation_text,
    build_shrink_setup_script,
    get_shrink_setup_button_label,
)
from sdtool.wsl_shrink import WslAvailabilityReport


def _report(code: str, distro_name: str = "Kali", missing_tools: tuple[str, ...] = ()) -> WslAvailabilityReport:
    return WslAvailabilityReport(
        is_ready=(code == "ready"),
        code=code,
        summary=f"summary {code}",
        detail=f"detail {code}",
        help_text=f"help {code}",
        distro_name=distro_name,
        missing_tools=missing_tools,
    )


def test_button_labels_use_stage_language() -> None:
    assert get_shrink_setup_button_label(_report("missing_wsl")) == "Start Step 1: Install WSL"
    assert get_shrink_setup_button_label(_report("missing_distro")) == "Start Step 2: Install Kali"
    assert get_shrink_setup_button_label(_report("missing_pishrink")) == "Start Step 3: Install PiShrink in Kali"
    assert get_shrink_setup_button_label(_report("ready")) == "Repair shrink support in Kali"


def test_build_shrink_setup_script_stage1_requires_reboot_even_without_prompt() -> None:
    script = build_shrink_setup_script(report=_report("missing_wsl"))
    assert "reboot Windows before continuing" in script
    assert "even if Windows does not explicitly ask" in script
    assert "Reboot Windows now before continuing" in script


def test_build_shrink_setup_script_stage2_explains_manual_window_close() -> None:
    script = build_shrink_setup_script(report=_report("missing_distro"))
    assert "If the distro window stays open at a prompt afterward" in script
    assert "type exit or close it manually" in script


def test_build_shrink_setup_script_stage3_mentions_required_packages_and_repo_help() -> None:
    script = build_shrink_setup_script(report=_report("missing_pishrink"))
    assert '$Distro = "Kali"' in script
    assert 'apt-get install -y curl parted e2fsprogs util-linux coreutils ca-certificates' in script
    assert "If apt reports repository or GPG errors" in script
    assert "The password will not be shown while you type." in script


def test_manual_help_and_confirmation_use_actual_distro_and_explain_next_steps() -> None:
    help_text = build_manual_shrink_setup_help(report=_report("missing_pishrink"))
    confirmation = build_shrink_setup_confirmation_text(_report("missing_pishrink"))
    assert "Open the Kali WSL distro" in help_text
    assert "If apt-get update fails with repository or GPG errors" in help_text
    assert "inside the WSL distro Kali" in confirmation
    assert "What happens next:" in confirmation
    assert "fix that distro's package sources and then run Step 3 again" in confirmation


def test_stage1_confirmation_and_help_always_tell_user_to_reboot() -> None:
    confirmation = build_shrink_setup_confirmation_text(_report("missing_wsl"))
    help_text = build_manual_shrink_setup_help(report=_report("missing_wsl"))
    assert "Reboot Windows after this step before continuing" in confirmation
    assert "even if Windows does not explicitly ask" in confirmation
    assert "Restart Windows after Step 1, even if Windows does not explicitly prompt for it." in help_text


def test_stage2_confirmation_explains_manual_close_if_prompt_remains() -> None:
    confirmation = build_shrink_setup_confirmation_text(_report("missing_distro"))
    assert "type exit if the Linux shell stays open" in confirmation
    assert "continue with Step 3" in confirmation
