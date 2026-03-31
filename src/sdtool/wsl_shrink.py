
from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
import locale
import os
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


@dataclass(frozen=True, slots=True)
class WslAvailabilityReport:
    is_ready: bool
    code: str
    summary: str
    detail: str
    help_text: str
    simulation: str | None = None
    distro_name: str | None = None


_SIM_ENV_NAME = "SDTOOL_SHRINK_SIMULATE_STATE"


def _clean_decoded_text(text: str) -> str:
    text = text.replace("\x00", "").replace("\ufeff", "")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return "".join(ch for ch in text if ch in "\n\t" or ord(ch) >= 32)


def _decode_subprocess_stream(data: bytes | str | None) -> str:
    if data is None:
        return ""

    if isinstance(data, str):
        return _clean_decoded_text(data)

    if not data:
        return ""

    candidates: list[str] = []
    if data.startswith((b"\xff\xfe", b"\xfe\xff")) or b"\x00" in data:
        candidates.extend(["utf-16", "utf-16le", "utf-16be"])

    preferred = locale.getpreferredencoding(False) or "utf-8"
    candidates.extend(["utf-8-sig", "utf-8", preferred, "cp1252"])

    seen: set[str] = set()
    for encoding in candidates:
        if encoding in seen:
            continue
        seen.add(encoding)
        try:
            return _clean_decoded_text(data.decode(encoding))
        except UnicodeDecodeError:
            continue

    return _clean_decoded_text(data.decode(preferred, errors="replace"))


def _run_command(
    argv: list[str],
    *,
    timeout_seconds: int | float | None = None,
) -> WslRunResult:
    result = subprocess.run(
        argv,
        capture_output=True,
        text=False,
        check=False,
        timeout=timeout_seconds,
    )
    return WslRunResult(
        returncode=result.returncode,
        stdout=_decode_subprocess_stream(result.stdout),
        stderr=_decode_subprocess_stream(result.stderr),
    )


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


def _default_distro_name(config: WslPiShrinkConfig | None = None) -> str:
    cfg = config or WslPiShrinkConfig()
    return cfg.distro or "Ubuntu"


def _select_distro_name(
    config: WslPiShrinkConfig | None = None,
    distros: list[str] | None = None,
) -> str:
    cfg = config or WslPiShrinkConfig()
    if cfg.distro:
        return cfg.distro
    if distros:
        return distros[0]
    return "Ubuntu"


def _detect_simulation_override(simulate_state: str | None = None) -> str | None:
    state = (simulate_state or os.getenv(_SIM_ENV_NAME, "")).strip().lower()
    return state or None


def _build_simulated_report(state: str) -> WslAvailabilityReport:
    if state == "ready":
        return WslAvailabilityReport(
            is_ready=True,
            code="ready",
            summary="Ready (simulated)",
            detail="Shrink readiness is being simulated as ready on this machine.",
            help_text=(
                "Simulation mode is active. Remove the environment variable "
                f"{_SIM_ENV_NAME} to return to real WSL/PiShrink detection."
            ),
            simulation=state,
        )

    summary_map = {
        "missing_wsl": "Step 1 of 3: Install WSL",
        "missing_distro": "Step 2 of 3: Install Linux distro",
        "missing_pishrink": "Step 3 of 3: Install PiShrink",
    }
    detail_map = {
        "missing_wsl": "Shrink readiness is being simulated as missing WSL on this machine.",
        "missing_distro": "Shrink readiness is being simulated as missing a Linux distribution.",
        "missing_pishrink": "Shrink readiness is being simulated as missing pishrink.sh.",
    }
    if state in summary_map:
        return WslAvailabilityReport(
            is_ready=False,
            code=state,
            summary=summary_map[state],
            detail=detail_map[state],
            help_text=(
                "Simulation mode is active. Remove the environment variable "
                f"{_SIM_ENV_NAME} to return to real WSL/PiShrink detection."
            ),
            simulation=state,
            distro_name="Ubuntu",
        )

    return WslAvailabilityReport(
        is_ready=False,
        code="invalid_simulation",
        summary="Unknown shrink simulation state",
        detail=(
            f"Unsupported value '{state}' for {_SIM_ENV_NAME}. "
            "Use ready, missing_wsl, missing_distro, or missing_pishrink."
        ),
        help_text=(
            "Remove the simulation environment variable or set it to one of: "
            "ready, missing_wsl, missing_distro, missing_pishrink."
        ),
        simulation=state,
    )


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
        'PARTS="$(lsblk -lnpo NAME,FSTYPE "$LOOPDEV" | grep -E " ext[234]$" | cut -d" " -f1)"',
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
    return _run_command(plan.argv, timeout_seconds=timeout_seconds)


def run_fsck_preflight(
    plan: WslPreflightPlan,
    timeout_seconds: int | float | None = None,
) -> WslRunResult:
    try:
        return _run_command(plan.argv, timeout_seconds=timeout_seconds)
    except subprocess.TimeoutExpired as exc:
        return WslRunResult(
            returncode=124,
            stdout=_decode_subprocess_stream(exc.stdout),
            stderr=_decode_subprocess_stream(exc.stderr) or f"Preflight timed out after {timeout_seconds} seconds.",
        )


def list_wsl_distros(config: WslPiShrinkConfig | None = None) -> list[str]:
    if sys.platform != "win32":
        return []

    cfg = config or WslPiShrinkConfig()
    result = _run_command([cfg.wsl_executable, "--list", "--quiet"])

    if result.returncode != 0:
        return []

    distros: list[str] = []
    for line in result.stdout.splitlines():
        name = line.strip().replace("\x00", "")
        if name and name not in distros:
            distros.append(name)
    return distros


def check_wsl_pishrink_available(config: WslPiShrinkConfig | None = None) -> bool:
    if sys.platform != "win32":
        return False

    cfg = config or WslPiShrinkConfig()
    selected_distro = _select_distro_name(cfg, list_wsl_distros(cfg))
    probe_cfg = replace(cfg, distro=selected_distro) if selected_distro else cfg
    probe_command = f"command -v {shlex.quote(probe_cfg.pishrink_command)} >/dev/null 2>&1"
    result = _run_command(_build_wsl_argv(probe_command, probe_cfg))
    return result.returncode == 0


def _normalize_wsl_probe_text(*parts: str) -> str:
    return _clean_decoded_text("\n".join(part for part in parts if part)).strip()


def _probe_indicates_missing_wsl(text: str) -> bool:
    lowered = text.lower()
    return (
        "optional component" in lowered
        or "wsl_e_wsl_optional_component_required" in lowered
        or "requires the windows subsystem for linux optional component" in lowered
        or "wsl was not found" in lowered
        or "is not recognized as the name of a cmdlet" in lowered
        or "windows subsystem for linux has not been enabled" in lowered
    )


def _probe_indicates_missing_distro(text: str) -> bool:
    lowered = text.lower()
    return (
        "no installed distributions" in lowered
        or "windows subsystem for linux has no installed distributions" in lowered
    )


def get_shrink_availability_report(
    config: WslPiShrinkConfig | None = None,
    *,
    simulate_state: str | None = None,
) -> WslAvailabilityReport:
    simulation = _detect_simulation_override(simulate_state)
    if simulation is not None:
        return _build_simulated_report(simulation)

    cfg = config or WslPiShrinkConfig()
    preferred_distro = _default_distro_name(cfg)

    if sys.platform != "win32":
        return WslAvailabilityReport(
            is_ready=False,
            code="non_windows",
            summary="Shrink is only available on Windows with WSL.",
            detail="The current platform is not Windows, so WSL-based PiShrink is unavailable.",
            help_text="Use the Windows build of the app on a system with WSL installed to enable shrink.",
        )

    try:
        probe = _run_command([cfg.wsl_executable, "--status"])
    except (subprocess.CalledProcessError, FileNotFoundError, OSError):
        return WslAvailabilityReport(
            is_ready=False,
            code="missing_wsl",
            summary="Step 1 of 3: Install WSL",
            detail="The app could not run wsl.exe on this machine.",
            help_text=(
                "Use the app's Install / Repair button to install WSL with minimal steps, or install it manually with "
                "'wsl --install --no-distribution'. A restart may be required."
            ),
            distro_name=preferred_distro,
        )

    probe_text = _normalize_wsl_probe_text(probe.stdout, probe.stderr)

    if probe.returncode != 0:
        if _probe_indicates_missing_wsl(probe_text):
            return WslAvailabilityReport(
                is_ready=False,
                code="missing_wsl",
                summary="Step 1 of 3: Install WSL",
                detail=probe_text or "The Windows Subsystem for Linux optional component is not enabled on this machine.",
                help_text=(
                    "Use the app's Install / Repair button to install or repair WSL, or install it manually with "
                    "'wsl --install --no-distribution'. A restart may be required."
                ),
                distro_name=preferred_distro,
            )

        if _probe_indicates_missing_distro(probe_text):
            return WslAvailabilityReport(
                is_ready=False,
                code="missing_distro",
                summary="Step 2 of 3: Install Linux distro",
                detail=f"WSL is installed, but no Linux distribution is ready. Install {preferred_distro}, launch it once, then return here for PiShrink installation.",
                help_text=(
                    f"Use the app's Install / Repair button to install {preferred_distro}, or run "
                    f"'wsl --install -d {preferred_distro}' manually. Launch the distro once after install "
                    "to finish first-run setup."
                ),
                distro_name=preferred_distro,
            )

        return WslAvailabilityReport(
            is_ready=False,
            code="missing_wsl",
            summary="Step 1 of 3: Install WSL",
            detail=probe_text or "wsl.exe reported an error while checking availability.",
            help_text=(
                "Use the app's Install / Repair button to install or repair WSL, or install it manually with "
                "'wsl --install --no-distribution'. A restart may be required."
            ),
            distro_name=preferred_distro,
        )

    distros = list_wsl_distros(cfg)
    selected_distro = _select_distro_name(cfg, distros)

    if not distros:
        return WslAvailabilityReport(
            is_ready=False,
            code="missing_distro",
            summary="Step 2 of 3: Install Linux distro",
            detail=f"WSL is installed, but no Linux distribution is ready. Install {selected_distro}, launch it once, then return here for PiShrink installation.",
            help_text=(
                f"Use the app's Install / Repair button to install {selected_distro}, or run "
                f"'wsl --install -d {selected_distro}' manually. Launch the distro once after install "
                "to finish first-run setup."
            ),
            distro_name=selected_distro,
        )

    if not check_wsl_pishrink_available(replace(cfg, distro=selected_distro)):
        return WslAvailabilityReport(
            is_ready=False,
            code="missing_pishrink",
            summary="Step 3 of 3: Install PiShrink",
            detail=f"WSL and the distro '{selected_distro}' are ready, but {cfg.pishrink_command} is not installed yet.",
            help_text=(
                "Use the app's Install / Repair button to install pishrink.sh into WSL, or install it manually inside your distro."
            ),
            distro_name=selected_distro,
        )

    return WslAvailabilityReport(
        is_ready=True,
        code="ready",
        summary="Ready",
        detail=f"WSL and PiShrink are available in the WSL distro '{selected_distro}'.",
        help_text=(
            f"To simulate a missing component on this same machine for testing, set {_SIM_ENV_NAME} to one of: "
            "missing_wsl, missing_distro, missing_pishrink, ready."
        ),
        distro_name=selected_distro,
    )


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
