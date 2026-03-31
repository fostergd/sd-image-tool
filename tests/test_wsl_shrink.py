
from __future__ import annotations

import sdtool.wsl_shrink as wsl_shrink
from sdtool.wsl_shrink import (
    WslPiShrinkConfig,
    build_pishrink_plan,
    check_wsl_pishrink_available,
    derive_shrunk_image_path,
    get_shrink_availability_report,
    list_wsl_distros,
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
    assert "Ubuntu" in plan.argv
    assert "root" in plan.argv


def test_build_pishrink_plan_can_shrink_in_place() -> None:
    cfg = WslPiShrinkConfig(keep_original=False)

    plan = build_pishrink_plan(r"D:\images\base.img", cfg)

    assert plan.output_path_windows == r"D:\images\base.img"
    assert "cp " not in plan.shell_command
    assert plan.shell_command.endswith("pishrink.sh /mnt/d/images/base.img")


def test_check_wsl_pishrink_available_returns_true_when_probe_succeeds(monkeypatch) -> None:
    monkeypatch.setattr(wsl_shrink.sys, "platform", "win32")
    monkeypatch.setattr(wsl_shrink, "list_wsl_distros", lambda config=None: ["Ubuntu"])

    def fake_run(argv, *, timeout_seconds=None):
        return wsl_shrink.WslRunResult(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(wsl_shrink, "_run_command", fake_run)

    assert check_wsl_pishrink_available(WslPiShrinkConfig())


def test_check_wsl_pishrink_available_returns_false_when_probe_fails(monkeypatch) -> None:
    monkeypatch.setattr(wsl_shrink.sys, "platform", "win32")
    monkeypatch.setattr(wsl_shrink, "list_wsl_distros", lambda config=None: ["Ubuntu"])

    def fake_run(argv, *, timeout_seconds=None):
        return wsl_shrink.WslRunResult(returncode=1, stdout="", stderr="not found")

    monkeypatch.setattr(wsl_shrink, "_run_command", fake_run)

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
    assert captured["text"] is True


def test_run_pishrink_plan_returns_completed_result(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_run(argv, *, timeout_seconds=None):
        captured["argv"] = argv
        captured["timeout"] = timeout_seconds
        return wsl_shrink.WslRunResult(returncode=0, stdout="ok", stderr="")

    monkeypatch.setattr(wsl_shrink, "_run_command", fake_run)

    plan = build_pishrink_plan(r"D:\images\demo.img")
    result = run_pishrink_plan(plan, timeout_seconds=120)

    assert result.succeeded
    assert result.stdout == "ok"
    assert captured["argv"][0] == "wsl.exe"
    assert captured["timeout"] == 120


def test_list_wsl_distros_parses_output(monkeypatch) -> None:
    monkeypatch.setattr(wsl_shrink.sys, "platform", "win32")

    def fake_run(argv, *, timeout_seconds=None):
        return wsl_shrink.WslRunResult(returncode=0, stdout="Ubuntu\nDebian\n", stderr="")

    monkeypatch.setattr(wsl_shrink, "_run_command", fake_run)

    assert list_wsl_distros() == ["Ubuntu", "Debian"]


def test_get_shrink_availability_report_missing_distro(monkeypatch) -> None:
    monkeypatch.setattr(wsl_shrink.sys, "platform", "win32")

    def fake_run(argv, *, timeout_seconds=None):
        return wsl_shrink.WslRunResult(returncode=0, stdout="WSL version: 2\n", stderr="")

    monkeypatch.setattr(wsl_shrink, "_run_command", fake_run)
    monkeypatch.setattr(wsl_shrink, "list_wsl_distros", lambda config=None: [])

    report = get_shrink_availability_report()

    assert not report.is_ready
    assert report.code == "missing_distro"


def test_get_shrink_availability_report_ready(monkeypatch) -> None:
    monkeypatch.setattr(wsl_shrink.sys, "platform", "win32")

    def fake_run(argv, *, timeout_seconds=None):
        return wsl_shrink.WslRunResult(returncode=0, stdout="WSL version: 2\n", stderr="")

    monkeypatch.setattr(wsl_shrink, "_run_command", fake_run)
    monkeypatch.setattr(wsl_shrink, "list_wsl_distros", lambda config=None: ["Ubuntu"])
    monkeypatch.setattr(wsl_shrink, "check_wsl_pishrink_available", lambda config=None: True)

    report = get_shrink_availability_report()

    assert report.is_ready
    assert report.code == "ready"
