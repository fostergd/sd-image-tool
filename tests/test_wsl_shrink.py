from __future__ import annotations

from types import SimpleNamespace

import sdtool.wsl_shrink as wsl_shrink
from sdtool.wsl_shrink import (
    WslPiShrinkConfig,
    build_pishrink_plan,
    check_wsl_pishrink_available,
    derive_shrunk_image_path,
    run_pishrink_plan,
    start_pishrink_process,
    windows_to_wsl_path,
)


def test_windows_to_wsl_path_converts_drive_and_separators() -> None:
    result = windows_to_wsl_path(r"D:\sd-image-tool\images\my image.img")
    assert result == "/mnt/d/sd-image-tool/images/my image.img"


def test_derive_shrunk_image_path_appends_suffix_before_extension() -> None:
    result = derive_shrunk_image_path(r"D:\images\raspios.img")
    assert result == r"D:\images\raspios-shrunk.img"


def test_build_pishrink_plan_keeps_original_by_default() -> None:
    cfg = WslPiShrinkConfig(distro="Ubuntu", pishrink_command="pishrink.sh", wsl_user="root", keep_original=True)

    plan = build_pishrink_plan(r"D:\images\my image.img", cfg)

    assert plan.image_path_windows == r"D:\images\my image.img"
    assert plan.output_path_windows == r"D:\images\my image-shrunk.img"
    assert "cp '/mnt/d/images/my image.img' '/mnt/d/images/my image-shrunk.img'" in plan.shell_command
    assert plan.argv[0] == "wsl.exe"
    assert "-d" in plan.argv
    assert "Ubuntu" in plan.argv
    assert "-u" in plan.argv
    assert "root" in plan.argv


def test_build_pishrink_plan_can_shrink_in_place() -> None:
    cfg = WslPiShrinkConfig(keep_original=False)

    plan = build_pishrink_plan(r"D:\images\base.img", cfg)

    assert plan.output_path_windows == r"D:\images\base.img"
    assert "cp " not in plan.shell_command
    assert plan.shell_command.endswith("pishrink.sh /mnt/d/images/base.img")
    assert "-u" in plan.argv
    assert "root" in plan.argv


def test_build_pishrink_plan_can_run_without_explicit_user() -> None:
    cfg = WslPiShrinkConfig(wsl_user=None)

    plan = build_pishrink_plan(r"D:\images\demo.img", cfg)

    assert "-u" not in plan.argv
    assert "root" not in plan.argv


def test_check_wsl_pishrink_available_returns_true_when_probe_succeeds(monkeypatch) -> None:
    def fake_run(*args, **kwargs):
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(wsl_shrink.subprocess, "run", fake_run)

    assert check_wsl_pishrink_available(WslPiShrinkConfig())


def test_check_wsl_pishrink_available_returns_false_when_probe_fails(monkeypatch) -> None:
    def fake_run(*args, **kwargs):
        return SimpleNamespace(returncode=1, stdout="", stderr="not found")

    monkeypatch.setattr(wsl_shrink.subprocess, "run", fake_run)

    assert not check_wsl_pishrink_available(WslPiShrinkConfig())


def test_start_pishrink_process_uses_popen(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class DummyProcess:
        pass

    def fake_popen(argv, stdout, stderr, text):
        captured["argv"] = argv
        captured["stdout"] = stdout
        captured["stderr"] = stderr
        captured["text"] = text
        return DummyProcess()

    monkeypatch.setattr(wsl_shrink.subprocess, "Popen", fake_popen)

    plan = build_pishrink_plan(r"D:\images\demo.img")
    result = start_pishrink_process(plan)

    assert isinstance(result, DummyProcess)
    assert captured["argv"][0] == "wsl.exe"
    assert "-u" in captured["argv"]
    assert "root" in captured["argv"]
    assert captured["text"] is True


def test_run_pishrink_plan_returns_completed_result(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_run(argv, capture_output, text, check, timeout):
        captured["argv"] = argv
        captured["timeout"] = timeout
        return SimpleNamespace(returncode=0, stdout="ok", stderr="")

    monkeypatch.setattr(wsl_shrink.subprocess, "run", fake_run)

    plan = build_pishrink_plan(r"D:\images\demo.img")
    result = run_pishrink_plan(plan, timeout_seconds=120)

    assert result.succeeded
    assert result.stdout == "ok"
    assert captured["argv"][0] == "wsl.exe"
    assert "-u" in captured["argv"]
    assert "root" in captured["argv"]
    assert captured["timeout"] == 120