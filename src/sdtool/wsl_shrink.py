from __future__ import annotations

from dataclasses import dataclass
from pathlib import PureWindowsPath
import shlex
import subprocess


@dataclass(slots=True, frozen=True)
class WslPiShrinkConfig:
    distro: str = "Ubuntu"
    pishrink_command: str = "pishrink.sh"
    use_sudo: bool = False
    keep_original: bool = True


@dataclass(slots=True, frozen=True)
class WslCommandPlan:
    distro: str
    image_path_windows: str
    image_path_wsl: str
    output_path_windows: str
    output_path_wsl: str
    shell_command: str
    argv: tuple[str, ...]


@dataclass(slots=True, frozen=True)
class WslRunResult:
    returncode: int
    stdout: str
    stderr: str

    @property
    def succeeded(self) -> bool:
        return self.returncode == 0


def _require_absolute_windows_path(path: str) -> PureWindowsPath:
    cleaned = path.strip()
    if not cleaned:
        raise ValueError("Image path cannot be empty.")

    win_path = PureWindowsPath(cleaned)
    if not win_path.drive:
        raise ValueError("Image path must be an absolute Windows path like D:\\images\\my.img.")

    return win_path


def windows_to_wsl_path(path: str) -> str:
    win_path = _require_absolute_windows_path(path)
    drive_letter = win_path.drive.rstrip(":").lower()
    tail_parts = list(win_path.parts[1:])

    if tail_parts:
        return f"/mnt/{drive_letter}/" + "/".join(tail_parts)

    return f"/mnt/{drive_letter}"


def derive_shrunk_image_path(path: str) -> str:
    win_path = _require_absolute_windows_path(path)

    if win_path.suffix:
        new_name = f"{win_path.stem}-shrunk{win_path.suffix}"
    else:
        new_name = f"{win_path.name}-shrunk"

    return str(win_path.with_name(new_name))


def build_pishrink_plan(
    image_path: str,
    config: WslPiShrinkConfig | None = None,
) -> WslCommandPlan:
    cfg = config or WslPiShrinkConfig()

    source_windows = str(_require_absolute_windows_path(image_path))
    source_wsl = windows_to_wsl_path(source_windows)

    if cfg.keep_original:
        output_windows = derive_shrunk_image_path(source_windows)
    else:
        output_windows = source_windows

    output_wsl = windows_to_wsl_path(output_windows)

    shell_steps = ["set -e"]

    if cfg.keep_original:
        shell_steps.append(f"cp {shlex.quote(source_wsl)} {shlex.quote(output_wsl)}")

    command_prefix = f"sudo {cfg.pishrink_command}" if cfg.use_sudo else cfg.pishrink_command
    shell_steps.append(f"{command_prefix} {shlex.quote(output_wsl)}")

    shell_command = " && ".join(shell_steps)
    argv = ("wsl.exe", "-d", cfg.distro, "bash", "-lc", shell_command)

    return WslCommandPlan(
        distro=cfg.distro,
        image_path_windows=source_windows,
        image_path_wsl=source_wsl,
        output_path_windows=output_windows,
        output_path_wsl=output_wsl,
        shell_command=shell_command,
        argv=argv,
    )


def check_wsl_pishrink_available(config: WslPiShrinkConfig | None = None) -> bool:
    cfg = config or WslPiShrinkConfig()
    probe_command = f"command -v {shlex.quote(cfg.pishrink_command)} >/dev/null 2>&1"
    argv = ["wsl.exe", "-d", cfg.distro, "bash", "-lc", probe_command]

    completed = subprocess.run(
        argv,
        capture_output=True,
        text=True,
        check=False,
    )
    return completed.returncode == 0


def run_pishrink_plan(
    plan: WslCommandPlan,
    timeout_seconds: int | None = None,
) -> WslRunResult:
    completed = subprocess.run(
        list(plan.argv),
        capture_output=True,
        text=True,
        check=False,
        timeout=timeout_seconds,
    )

    return WslRunResult(
        returncode=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
    )