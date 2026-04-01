from __future__ import annotations

import sdtool.windows_elevation as windows_elevation


def test_build_relaunch_command_for_source(monkeypatch) -> None:
    monkeypatch.setattr(windows_elevation.sys, "frozen", False, raising=False)
    monkeypatch.setattr(windows_elevation.sys, "executable", r"C:\Python312\python.exe")

    executable, parameters = windows_elevation._build_relaunch_command(["--demo"])

    assert executable == r"C:\Python312\python.exe"
    assert "-m sdtool.app --demo" in parameters


def test_build_relaunch_command_for_frozen(monkeypatch) -> None:
    monkeypatch.setattr(windows_elevation.sys, "frozen", True, raising=False)
    monkeypatch.setattr(windows_elevation.sys, "executable", r"C:\Apps\SDImageTool.exe")

    executable, parameters = windows_elevation._build_relaunch_command(["--demo"])

    assert executable == r"C:\Apps\SDImageTool.exe"
    assert "--demo" in parameters


def test_ensure_admin_or_relaunch_returns_true_when_already_elevated(monkeypatch) -> None:
    monkeypatch.setattr(windows_elevation.sys, "platform", "win32")
    monkeypatch.setattr(windows_elevation, "is_current_process_elevated", lambda: True)

    should_continue, detail = windows_elevation.ensure_admin_or_relaunch([])

    assert should_continue is True
    assert detail == "Already elevated."


def test_relaunch_current_process_as_admin_returns_failure_when_shell_execute_fails(monkeypatch) -> None:
    monkeypatch.setattr(windows_elevation.sys, "platform", "win32")

    class FakeShell32:
        @staticmethod
        def ShellExecuteW(*args):
            return 31

    class FakeWindll:
        shell32 = FakeShell32()

    monkeypatch.setattr(windows_elevation.ctypes, "windll", FakeWindll())
    monkeypatch.setattr(
        windows_elevation,
        "_build_relaunch_command",
        lambda argv=None: (r"C:\Python312\python.exe", "-m sdtool.app"),
    )

    launched, detail = windows_elevation.relaunch_current_process_as_admin([])

    assert launched is False
    assert "ShellExecuteW" in detail
