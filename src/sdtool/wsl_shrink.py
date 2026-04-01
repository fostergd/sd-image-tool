from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os
import shlex
import subprocess
import sys

_REQUIRED_PISHRINK_TOOLS = (
    "parted",
    "losetup",
    "tune2fs",
    "md5sum",
    "e2fsck",
    "resize2fs",
)
_SIM_ENV_NAME = "SDTOOL_SHRINK_SIMULATE_STATE"


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
    missing_tools: tuple[str, ...] = ()


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


def _normalize_probe_text(*parts: str) -> str:
    text = "\n".join(part for part in parts if part)
    return text.replace("\x00", "").strip()


def _default_distro_name(config: WslPiShrinkConfig | None = None) -> str:
    cfg = config or WslPiShrinkConfig()
    return cfg.distro or "Ubuntu"


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
            help_text=f"Remove {_SIM_ENV_NAME} to return to real WSL/PiShrink detection.",
            simulation=state,
            distro_name="Ubuntu",
        )
    if state == "missing_wsl":
        return WslAvailabilityReport(
            is_ready=False,
            code="missing_wsl",
            summary="Step 1 of 3: Install WSL",
            detail="Shrink readiness is being simulated as missing WSL on this machine.",
            help_text=f"Remove {_SIM_ENV_NAME} to return to real WSL/PiShrink detection.",
            simulation=state,
            distro_name="Ubuntu",
        )
    if state == "missing_distro":
        return WslAvailabilityReport(
            is_ready=False,
            code="missing_distro",
            summary="Step 2 of 3: Install Linux distro",
            detail="Shrink readiness is being simulated as missing a Linux distribution.",
            help_text=f"Remove {_SIM_ENV_NAME} to return to real WSL/PiShrink detection.",
            simulation=state,
            distro_name="Ubuntu",
        )
    if state == "missing_pishrink":
        return WslAvailabilityReport(
            is_ready=False,
            code="missing_pishrink",
            summary="Step 3 of 3: Install PiShrink",
            detail="Shrink readiness is being simulated as missing PiShrink or required tools.",
            help_text=f"Remove {_SIM_ENV_NAME} to return to real WSL/PiShrink detection.",
            simulation=state,
            distro_name="Ubuntu",
        )
    return WslAvailabilityReport(
        is_ready=False,
        code="invalid_simulation",
        summary="Unknown shrink simulation state",
        detail=(
            f"Unsupported value '{state}' for {_SIM_ENV_NAME}. Use ready, missing_wsl, missing_distro, or missing_pishrink."
        ),
        help_text=f"Remove {_SIM_ENV_NAME} or set it to ready, missing_wsl, missing_distro, or missing_pishrink.",
        simulation=state,
        distro_name="Ubuntu",
    )


def build_pishrink_plan(image_path_windows: str, config: WslPiShrinkConfig | None = None) -> WslCommandPlan:
    cfg = config or WslPiShrinkConfig()
    image_path = Path(image_path_windows)
    if not image_path.is_absolute():
        raise ValueError("Shrink requires an absolute Windows image path.")

    output_path = Path(derive_shrunk_image_path(str(image_path))) if cfg.keep_original else image_path
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
        shell_steps = ["set -e", f"{shlex.quote(cfg.pishrink_command)} {shlex.quote(output_path_wsl)}"]

    shell_command = " && ".join(shell_steps)
    return WslCommandPlan(
        image_path_windows=str(image_path),
        image_path_wsl=image_path_wsl,
        output_path_windows=str(output_path),
        output_path_wsl=output_path_wsl,
        shell_command=shell_command,
        argv=_build_wsl_argv(shell_command, cfg),
    )


def build_fsck_preflight_plan(image_path_windows: str, config: WslPiShrinkConfig | None = None) -> WslPreflightPlan:
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
        'PARTS="$(lsblk -lnpo NAME,FSTYPE "$LOOPDEV" | awk "$2 ~ /^ext[234]$/ {print $1}")"',
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
    return WslPreflightPlan(
        image_path_windows=str(image_path),
        image_path_wsl=image_path_wsl,
        shell_command=shell_command,
        argv=_build_wsl_argv(shell_command, cfg),
    )


def build_wsl_command(plan: WslCommandPlan, config: WslPiShrinkConfig | None = None) -> list[str]:
    cfg = config or WslPiShrinkConfig()
    return _build_wsl_argv(plan.shell_command, cfg)


def run_pishrink_plan(plan: WslCommandPlan, timeout_seconds: int | float | None = None) -> WslRunResult:
    result = subprocess.run(plan.argv, capture_output=True, text=True, check=False, timeout=timeout_seconds)
    return WslRunResult(returncode=result.returncode, stdout=result.stdout, stderr=result.stderr)


def run_fsck_preflight(plan: WslPreflightPlan, timeout_seconds: int | float | None = None) -> WslRunResult:
    try:
        result = subprocess.run(plan.argv, capture_output=True, text=True, check=False, timeout=timeout_seconds)
        return WslRunResult(returncode=result.returncode, stdout=result.stdout, stderr=result.stderr)
    except subprocess.TimeoutExpired as exc:
        return WslRunResult(returncode=124, stdout=exc.stdout or "", stderr=exc.stderr or f"Preflight timed out after {timeout_seconds} seconds.")


def list_wsl_distros(config: WslPiShrinkConfig | None = None) -> list[str]:
    if sys.platform != "win32":
        return []
    cfg = config or WslPiShrinkConfig()
    try:
        result = subprocess.run([cfg.wsl_executable, "--list", "--quiet"], capture_output=True, text=True, check=False)
    except (subprocess.CalledProcessError, FileNotFoundError, OSError):
        return []
    if result.returncode != 0:
        return []
    distros: list[str] = []
    for line in result.stdout.splitlines():
        name = line.strip().replace("\x00", "")
        if name and name not in distros:
            distros.append(name)
    return distros


def _probe_indicates_missing_wsl(text: str) -> bool:
    lowered = text.lower()
    return (
        "optional component" in lowered
        or "wsl_e_wsl_optional_component_required" in lowered
        or "requires the windows subsystem for linux optional component" in lowered
        or "wsl was not found" in lowered
        or "is not recognized as the name of a cmdlet" in lowered
    )


def _probe_indicates_missing_distro(text: str) -> bool:
    lowered = text.lower()
    return "no installed distributions" in lowered or "windows subsystem for linux has no installed distributions" in lowered


def _resolve_distro_name(config: WslPiShrinkConfig, distros: list[str]) -> str:
    if config.distro:
        return config.distro
    if distros:
        return distros[0]
    return "Ubuntu"


def _config_for_distro(base_config: WslPiShrinkConfig, distro_name: str) -> WslPiShrinkConfig:
    return WslPiShrinkConfig(
        wsl_executable=base_config.wsl_executable,
        shell_executable=base_config.shell_executable,
        shell_login_flag=base_config.shell_login_flag,
        pishrink_command=base_config.pishrink_command,
        distro=distro_name,
        wsl_user=base_config.wsl_user,
        keep_original=base_config.keep_original,
    )


def _probe_wsl_commands(commands: tuple[str, ...], config: WslPiShrinkConfig) -> tuple[bool, tuple[str, ...]]:
    check_parts = [f"command -v {shlex.quote(cmd)} >/dev/null 2>&1" for cmd in commands]
    try:
        result = subprocess.run(_build_wsl_argv(" && ".join(check_parts), config), capture_output=True, text=True, check=False)
    except (subprocess.CalledProcessError, FileNotFoundError, OSError):
        return False, commands
    if result.returncode == 0:
        return True, ()

    missing: list[str] = []
    for command in commands:
        try:
            sub = subprocess.run(_build_wsl_argv(f"command -v {shlex.quote(command)} >/dev/null 2>&1", config), capture_output=True, text=True, check=False)
        except (subprocess.CalledProcessError, FileNotFoundError, OSError):
            missing.append(command)
            continue
        if sub.returncode != 0:
            missing.append(command)
    return len(missing) == 0, tuple(missing)


def check_wsl_pishrink_available(config: WslPiShrinkConfig | None = None) -> bool:
    return get_shrink_availability_report(config).is_ready


def get_shrink_availability_report(config: WslPiShrinkConfig | None = None, *, simulate_state: str | None = None) -> WslAvailabilityReport:
    simulation = _detect_simulation_override(simulate_state)
    if simulation is not None:
        return _build_simulated_report(simulation)

    cfg = config or WslPiShrinkConfig()
    default_distro = _default_distro_name(cfg)

    if sys.platform != "win32":
        return WslAvailabilityReport(
            is_ready=False,
            code="non_windows",
            summary="Shrink is only available on Windows with WSL.",
            detail="The current platform is not Windows, so WSL-based PiShrink is unavailable.",
            help_text="Use the Windows build of the app on a system with WSL installed to enable shrink.",
            distro_name=default_distro,
        )

    try:
        probe = subprocess.run([cfg.wsl_executable, "--status"], capture_output=True, text=True, check=False)
    except (subprocess.CalledProcessError, FileNotFoundError, OSError):
        return WslAvailabilityReport(
            is_ready=False,
            code="missing_wsl",
            summary="Step 1 of 3: Install WSL",
            detail="The app could not run wsl.exe on this machine.",
            help_text="Use the app's Install / Repair button to install WSL. A restart may be required.",
            distro_name=default_distro,
        )

    probe_text = _normalize_probe_text(probe.stdout, probe.stderr)
    if probe.returncode != 0:
        if _probe_indicates_missing_wsl(probe_text):
            return WslAvailabilityReport(
                is_ready=False,
                code="missing_wsl",
                summary="Step 1 of 3: Install WSL",
                detail=probe_text or "The Windows Subsystem for Linux optional component is not enabled on this machine.",
                help_text="Use the app's Install / Repair button to install or repair WSL. A restart may be required.",
                distro_name=default_distro,
            )
        if _probe_indicates_missing_distro(probe_text):
            return WslAvailabilityReport(
                is_ready=False,
                code="missing_distro",
                summary="Step 2 of 3: Install Linux distro",
                detail=f"WSL is installed, but no Linux distribution is ready. Install {default_distro}, launch it once, then return here for PiShrink installation.",
                help_text=f"Use the app's Install / Repair button to install {default_distro}, then launch it once for first-run setup.",
                distro_name=default_distro,
            )
        return WslAvailabilityReport(
            is_ready=False,
            code="missing_wsl",
            summary="Step 1 of 3: Install WSL",
            detail=probe_text or "wsl.exe reported an error while checking availability.",
            help_text="Use the app's Install / Repair button to install or repair WSL.",
            distro_name=default_distro,
        )

    distros = list_wsl_distros(cfg)
    distro_name = _resolve_distro_name(cfg, distros)
    if not distros:
        return WslAvailabilityReport(
            is_ready=False,
            code="missing_distro",
            summary="Step 2 of 3: Install Linux distro",
            detail=f"WSL is installed, but no Linux distribution is ready. Install {distro_name}, launch it once, then return here for PiShrink installation.",
            help_text=f"Use the app's Install / Repair button to install {distro_name}, then launch it once for first-run setup.",
            distro_name=distro_name,
        )

    distro_cfg = _config_for_distro(cfg, distro_name)
    all_tools = (cfg.pishrink_command,) + _REQUIRED_PISHRINK_TOOLS
    tools_ready, missing_tools = _probe_wsl_commands(all_tools, distro_cfg)
    if not tools_ready:
        missing_list = ", ".join(missing_tools) if missing_tools else cfg.pishrink_command
        return WslAvailabilityReport(
            is_ready=False,
            code="missing_pishrink",
            summary="Step 3 of 3: Install PiShrink",
            detail=f"WSL and the distro '{distro_name}' are ready, but shrink support is incomplete. Missing items: {missing_list}.",
            help_text="Use the app's Install / Repair button to install or repair PiShrink and its required tools inside WSL.",
            distro_name=distro_name,
            missing_tools=missing_tools,
        )

    return WslAvailabilityReport(
        is_ready=True,
        code="ready",
        summary="Ready",
        detail=f"WSL, PiShrink, and required tools are available in the WSL distro '{distro_name}'.",
        help_text=f"To simulate a missing component on this same machine for testing, set {_SIM_ENV_NAME} to missing_wsl, missing_distro, missing_pishrink, or ready.",
        distro_name=distro_name,
    )


def start_pishrink_process(plan: WslCommandPlan, config: WslPiShrinkConfig | None = None) -> subprocess.Popen[str]:
    argv = plan.argv if config is None else _build_wsl_argv(plan.shell_command, config)
    return subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
