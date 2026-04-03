from __future__ import annotations

from types import SimpleNamespace

import sdtool.wsl_shrink as wsl_shrink
from sdtool.wsl_shrink import (
    WslPiShrinkConfig,
    build_pishrink_plan,
    check_wsl_pishrink_available,
    derive_shrunk_image_path,
    get_shrink_availability_report,
    run_pishrink_plan,
    start_pishrink_process,
    windows_to_wsl_path,
)


def test_windows_to_wsl_path_converts_drive_and_separators() -> None:
    assert windows_to_wsl_path(r"D:\sd-image-tool\images\my image.img") == "/mnt/d/sd-image-tool/images/my image.img"


def test_derive_shrunk_image_path_appends_suffix_before_extension() -> None:
    assert derive_shrunk_image_path(r"D:\images\raspios.img") == r"D:\images\raspios-shrunk.img"


def test_build_pishrink_plan_keeps_original_by_default() -> None:
    cfg = WslPiShrinkConfig(distro="Ubuntu", pishrink_command="pishrink.sh", wsl_user="root", keep_original=True)
    plan = build_pishrink_plan(r"D:\images\my image.img", cfg)
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


def test_check_wsl_pishrink_available_false_when_report_not_ready(monkeypatch) -> None:
    monkeypatch.setattr(wsl_shrink, "get_shrink_availability_report", lambda config=None: SimpleNamespace(is_ready=False))
    assert not check_wsl_pishrink_available(WslPiShrinkConfig())


def test_check_wsl_pishrink_available_true_when_report_ready(monkeypatch) -> None:
    monkeypatch.setattr(wsl_shrink, "get_shrink_availability_report", lambda config=None: SimpleNamespace(is_ready=True))
    assert check_wsl_pishrink_available(WslPiShrinkConfig())


def test_get_shrink_availability_report_marks_missing_tools(monkeypatch) -> None:
    monkeypatch.setattr(wsl_shrink.sys, "platform", "win32")

    def fake_run(argv, capture_output, text, check, **kwargs):
        if argv[1:] == ["--status"]:
            return SimpleNamespace(returncode=0, stdout="Default Distribution: Kali\n", stderr="")
        if argv[1:] == ["--list", "--quiet"]:
            return SimpleNamespace(returncode=0, stdout="kali-linux\n", stderr="")
        cmd = argv[-1]
        if "command -v pishrink.sh" in cmd and "parted" in cmd:
            return SimpleNamespace(returncode=1, stdout="", stderr="")
        if cmd == "command -v pishrink.sh >/dev/null 2>&1":
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        if cmd == "command -v parted >/dev/null 2>&1":
            return SimpleNamespace(returncode=1, stdout="", stderr="")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(wsl_shrink.subprocess, "run", fake_run)
    report = get_shrink_availability_report(WslPiShrinkConfig())
    assert not report.is_ready
    assert report.code == "missing_pishrink"
    assert report.summary == "Step 3 of 3: Install PiShrink and tools"
    assert "Start Step 3" in report.detail
    assert "parted" in report.detail
    assert report.distro_name == "kali-linux"


def test_start_pishrink_process_uses_popen(monkeypatch) -> None:
    captured = {}

    class DummyProcess:
        pass

    def fake_popen(argv, stdout, stderr, text):
        captured["argv"] = argv
        return DummyProcess()

    monkeypatch.setattr(wsl_shrink.subprocess, "Popen", fake_popen)
    plan = build_pishrink_plan(r"D:\images\demo.img")
    result = start_pishrink_process(plan)
    assert isinstance(result, DummyProcess)
    assert captured["argv"][0] == "wsl.exe"


def test_run_pishrink_plan_returns_completed_result(monkeypatch) -> None:
    def fake_run(argv, capture_output, text, check, timeout):
        return SimpleNamespace(returncode=0, stdout="ok", stderr="")

    monkeypatch.setattr(wsl_shrink.subprocess, "run", fake_run)
    plan = build_pishrink_plan(r"D:\images\demo.img")
    result = run_pishrink_plan(plan, timeout_seconds=120)
    assert result.succeeded
    assert result.stdout == "ok"
