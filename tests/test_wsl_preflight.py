from __future__ import annotations

from sdtool.wsl_shrink import WslPiShrinkConfig, build_fsck_preflight_plan


def test_build_fsck_preflight_plan_contains_expected_commands() -> None:
    plan = build_fsck_preflight_plan(r"D:\images\demo.img", WslPiShrinkConfig(distro="Ubuntu"))
    assert plan.image_path_wsl == "/mnt/d/images/demo.img"
    assert "losetup --find --show --partscan" in plan.shell_command
    assert "e2fsck -fn" in plan.shell_command
    assert "Ubuntu" in plan.argv
