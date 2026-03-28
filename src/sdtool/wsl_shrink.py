from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import shlex
import subprocess
import sys


@dataclass(frozen=True, slots=True)
class WslPiShrinkConfig:
    wsl_executable: str = "wsl.exe"
    shell_executable: str = "bash"
    shell_login_flag: str = "-lc"
    pishrink_command: str = "pishrink.sh"
    distro: str | None = None
    wsl_user: str | None = "root"
    keep_original: bool = True


@dataclass(frozen=True, slots=True)
class WslCommandPlan:
    image_path_windows: str
    image_path_wsl: str
    output_path_windows: str
    output_path_wsl: str
    shell_command: str
    argv: list[str]


@dataclass(frozen=True, slots=True)
class WslPreflightPlan:
    image_path_windows: str
    image_path_wsl: str
    shell_command: str
    argv: list[str]


@dataclass(frozen=True, slots=True)
class WslRunResult:
    returncode: int
    stdout: str
    stderr: str

    @property
    def succeeded(self) -> bool:
        return self.returncode == 0


def windows_to_wsl_path(path: str) -> str:
    text = str(path).strip().replace("/", "\\")
    if len(text) < 3 or text[1] != ":":
        raise ValueError(f"Expected an absolute Windows path, got: {path}")

    drive_letter = text[0].lower()
    tail = text[2:].replace("\\", "/").lstrip("/")
    return f"/mnt/{drive_letter}/{tail}"


def _windows_to_wsl_path(path: str) -> str:
    return windows_to_wsl_path(path)


def derive_shrunk_image_path(image_path_windows: str) -> str:
    image_path = Path(image_path_windows)
    suffix = image_path.suffix or ".img"
    return str(image_path.with_name(f"{image_path.stem}-shrunk{suffix}"))


def _build_wsl_argv(shell_command: str, config: WslPiShrinkConfig) -> list[str]:
    argv: list[str] = [config.wsl_executable]

    if config.distro:
        argv.extend(["-d", config.distro])

    if config.wsl_user:
        argv.extend(["-u", config.wsl_user])

    argv.extend([config.shell_executable, config.shell_login_flag, shell_command])
    return argv


def build_pishrink_plan(
    image_path_windows: str,
    config: WslPiShrinkConfig | None = None,
) -> WslCommandPlan:
    cfg = config or WslPiShrinkConfig()

    image_path = Path(image_path_windows)
    if not image_path.is_absolute():
        raise ValueError("Shrink requires an absolute Windows image path.")

    if cfg.keep_original:
        output_path = Path(derive_shrunk_image_path(str(image_path)))
    else:
        output_path = image_path

    image_path_wsl = windows_to_wsl_path(str(image_path))
    output_path_wsl = windows_to_wsl_path(str(output_path))

    if cfg.keep_original:
        shell_steps = [
            "set -e",
            "echo '[sdtool] copying source image to shrink output path'",
            f"cp {shlex.quote(image_path_wsl)} {shlex.quote(output_path_wsl)}",
            "echo '[sdtool] starting PiShrink'",
            f"{shlex.quote(cfg.pishrink_command)} {shlex.quote(output_path_wsl)}",
            "echo '[sdtool] PiShrink finished'",
        ]
    else:
        shell_steps = [
            "set -e",
            f"{shlex.quote(cfg.pishrink_command)} {shlex.quote(output_path_wsl)}",
        ]

    shell_command = " && ".join(shell_steps)
    argv = _build_wsl_argv(shell_command, cfg)

    return WslCommandPlan(
        image_path_windows=str(image_path),
        image_path_wsl=image_path_wsl,
        output_path_windows=str(output_path),
        output_path_wsl=output_path_wsl,
        shell_command=shell_command,
        argv=argv,
    )


def build_fsck_preflight_plan(
    image_path_windows: str,
    config: WslPiShrinkConfig | None = None,
) -> WslPreflightPlan:
    cfg = config or WslPiShrinkConfig()

    image_path = Path(image_path_windows)
    if not image_path.is_absolute():
        raise ValueError("Shrink preflight requires an absolute Windows image path.")

    image_path_wsl = windows_to_wsl_path(str(image_path))

    shell_lines = [
        "set -euo pipefail",
        f"IMG={shlex.quote(image_path_wsl)}",
        'LOOPDEV=""',
        "cleanup() {",
        '  if [ -n "${LOOPDEV:-}" ]; then',
        '    losetup -d "$LOOPDEV" >/dev/null 2>&1 || true',
        "  fi",
        "}",
        "trap cleanup EXIT",
        'echo "[sdtool] attaching image to loop device"',
        'LOOPDEV="$(losetup --find --show --partscan "$IMG")"',
        'if [ -z "$LOOPDEV" ]; then',
        '  echo "[sdtool] failed to attach image to loop device"',
        "  exit 21",
        "fi",
        'echo "[sdtool] scanning ext filesystem partitions"',
        'PARTS="$(lsblk -lnpo NAME,FSTYPE "$LOOPDEV" | awk \'$2 ~ /^ext[234]$/ {print $1}\')"',
        'if [ -z "$PARTS" ]; then',
        '  echo "[sdtool] no ext filesystem partitions found in image"',
        "  exit 20",
        "fi",
        'while IFS= read -r PART; do',
        '  [ -n "$PART" ] || continue',
        '  echo "[sdtool] preflight e2fsck -fn $PART"',
        "  set +e",
        '  e2fsck -fn "$PART"',
        "  RC=$?",
        "  set -e",
        '  echo "[sdtool] e2fsck exit code $RC for $PART"',
        '  if [ "$RC" -gt 1 ]; then',
        '    exit "$RC"',
        "  fi",
        'done <<< "$PARTS"',
        'echo "[sdtool] preflight passed"',
    ]

    shell_command = "\n".join(shell_lines)
    argv = _build_wsl_argv(shell_command, cfg)

    return WslPreflightPlan(
        image_path_windows=str(image_path),
        image_path_wsl=image_path_wsl,
        shell_command=shell_command,
        argv=argv,
    )


def build_wsl_command(
    plan: WslCommandPlan,
    config: WslPiShrinkConfig | None = None,
) -> list[str]:
    cfg = config or WslPiShrinkConfig()
    return _build_wsl_argv(plan.shell_command, cfg)


def run_pishrink_plan(
    plan: WslCommandPlan,
    timeout_seconds: int | float | None = None,
) -> WslRunResult:
    result = subprocess.run(
        plan.argv,
        capture_output=True,
        text=True,
        check=False,
        timeout=timeout_seconds,
    )
    return WslRunResult(
        returncode=result.returncode,
        stdout=result.stdout,
        stderr=result.stderr,
    )


def run_fsck_preflight(
    plan: WslPreflightPlan,
    timeout_seconds: int | float | None = None,
) -> WslRunResult:
    try:
        result = subprocess.run(
            plan.argv,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout_seconds,
        )
        return WslRunResult(
            returncode=result.returncode,
            stdout=result.stdout,
            stderr=result.stderr,
        )
    except subprocess.TimeoutExpired as exc:
        return WslRunResult(
            returncode=124,
            stdout=exc.stdout or "",
            stderr=exc.stderr or f"Preflight timed out after {timeout_seconds} seconds.",
        )


def check_wsl_pishrink_available(config: WslPiShrinkConfig | None = None) -> bool:
    if sys.platform != "win32":
        return False

    cfg = config or WslPiShrinkConfig()
    probe_command = f"command -v {shlex.quote(cfg.pishrink_command)} >/dev/null 2>&1"
    argv = _build_wsl_argv(probe_command, cfg)

    try:
        result = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            check=False,
        )
    except (FileNotFoundError, OSError):
        return False

    return result.returncode == 0


def start_pishrink_process(
    plan: WslCommandPlan,
    config: WslPiShrinkConfig | None = None,
) -> subprocess.Popen[str]:
    argv = plan.argv if config is None else _build_wsl_argv(plan.shell_command, config)

    return subprocess.Popen(
        argv,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
