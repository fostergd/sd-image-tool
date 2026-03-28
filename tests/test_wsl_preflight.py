from __future__ import annotations

from types import SimpleNamespace
import subprocess

import sdtool.wsl_shrink as wsl_shrink
from sdtool.wsl_shrink import (
    WslPiShrinkConfig,
    build_fsck_preflight_plan,
    run_fsck_preflight,
)


def test_build_fsck_preflight_plan_contains_expected_commands() -> None:
    cfg = WslPiShrinkConfig(distro="Ubuntu", wsl_user="root")
