
from __future__ import annotations

import subprocess

import sdtool.wsl_shrink as wsl_shrink
from sdtool.wsl_shrink import (
    WslPiShrinkConfig,
    build_fsck_preflight_plan,
    run_fsck_preflight,
)


def test_build_fsck_preflight_plan_contains_expected_commands() -> None:
    cfg = WslPiShrinkConfig(distro="Ubuntu", wsl_user="root")

    plan = build_fsck_preflight_plan(r"D:\images\demo.img", cfg)

    assert plan.image_path_windows == r"D:\images\demo.img"
    assert plan.image_path_wsl == "/mnt/d/images/demo.img"
    assert "losetup --find --show --partscan" in plan.shell_command
    assert "e2fsck -fn" in plan.shell_command
    assert "Ubuntu" in plan.argv
    assert "root" in plan.argv


def test_run_fsck_preflight_returns_completed_result(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_run(argv, *, timeout_seconds=None):
        captured["argv"] = argv
        captured["timeout"] = timeout_seconds
        return wsl_shrink.WslRunResult(returncode=0, stdout="ok", stderr="")

    monkeypatch.setattr(wsl_shrink, "_run_command", fake_run)

    plan = build_fsck_preflight_plan(r"D:\images\demo.img")
    result = run_fsck_preflight(plan, timeout_seconds=120)

    assert result.succeeded
    assert result.stdout == "ok"
    assert captured["argv"][0] == "wsl.exe"
    assert captured["timeout"] == 120


def test_run_fsck_preflight_timeout_returns_failure(monkeypatch) -> None:
    def fake_run(argv, *, timeout_seconds=None):
        raise subprocess.TimeoutExpired(cmd=argv, timeout=timeout_seconds, output=b"before", stderr=b"timed out")

    monkeypatch.setattr(wsl_shrink, "_run_command", fake_run)

    plan = build_fsck_preflight_plan(r"D:\images\demo.img")
    result = run_fsck_preflight(plan, timeout_seconds=60)

    assert not result.succeeded
    assert result.returncode == 124
    assert "timed out" in result.stderr.lower()
