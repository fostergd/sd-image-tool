from __future__ import annotations

import ctypes
import subprocess
import sys
from typing import Sequence


def is_current_process_elevated() -> bool:
    if sys.platform != "win32":
        return True

    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def _build_relaunch_command(argv: Sequence[str] | None = None) -> tuple[str, str]:
    forwarded = list(argv if argv is not None else sys.argv[1:])

    if getattr(sys, "frozen", False):
        executable = sys.executable
        parameters = subprocess.list2cmdline(forwarded)
        return executable, parameters

    executable = sys.executable
    parameters = subprocess.list2cmdline(["-m", "sdtool.app", *forwarded])
    return executable, parameters


def relaunch_current_process_as_admin(argv: Sequence[str] | None = None) -> tuple[bool, str]:
    if sys.platform != "win32":
        return True, "Administrator relaunch is only required on Windows."

    executable, parameters = _build_relaunch_command(argv)

    try:
        rc = ctypes.windll.shell32.ShellExecuteW(
            None,
            "runas",
            executable,
            parameters,
            None,
            1,
        )
    except Exception as exc:
        return False, f"Failed to request elevation: {exc}"

    if rc <= 32:
        return False, f"Windows did not start the elevated process (ShellExecuteW={rc})."

    return True, "Started elevated instance."


def ensure_admin_or_relaunch(argv: Sequence[str] | None = None) -> tuple[bool, str]:
    if sys.platform != "win32":
        return True, "Non-Windows platform."

    if is_current_process_elevated():
        return True, "Already elevated."

    launched, detail = relaunch_current_process_as_admin(argv)
    if launched:
        return False, detail

    return False, detail
