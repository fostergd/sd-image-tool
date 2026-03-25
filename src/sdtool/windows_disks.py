from __future__ import annotations

import json
import logging
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

from sdtool.models import DeviceInfo

LOG = logging.getLogger(__name__)

_ALWAYS_ALLOWED_BUS_TYPES = {"USB", "SD"}
_SCSI_CARD_READER_HINTS = (
    "CARDREADER",
    "CARD READER",
    "SD",
    "MMC",
    "MEMORYSTICK",
    "MEMORY STICK",
)


def _normalize_drive_root(value: Path | str | None) -> str | None:
    if value is None:
        return None

    text = str(value).strip()
    if not text:
        return None

    normalized = text.replace("/", "\\")
    match = re.match(r"^([A-Za-z]):", normalized)
    if match:
        return f"{match.group(1).upper()}:"

    try:
        anchor = Path(normalized).anchor
    except Exception:
        return None

    if not anchor:
        return None

    anchor = anchor.replace("/", "\\")
    match = re.match(r"^([A-Za-z]):", anchor)
    if not match:
        return None

    return f"{match.group(1).upper()}:"


def _normalize_drive_letters(value: Any) -> set[str]:
    if value is None:
        return set()

    if isinstance(value, str):
        values = [value]
    elif isinstance(value, (list, tuple, set)):
        values = list(value)
    else:
        return set()

    normalized: set[str] = set()
    for item in values:
        drive_root = _normalize_drive_root(item)
        if drive_root:
            normalized.add(drive_root)
    return normalized


def _looks_like_scsi_card_reader(friendly_name: str) -> bool:
    upper_name = friendly_name.upper()
    return any(hint in upper_name for hint in _SCSI_CARD_READER_HINTS)


def _is_candidate_removable_disk(record: dict[str, Any]) -> bool:
    if bool(record.get("IsSystem")):
        return False

    if bool(record.get("IsBoot")):
        return False

    bus_type = str(record.get("BusType", "")).strip().upper()
    if bus_type in _ALWAYS_ALLOWED_BUS_TYPES:
        return True

    if bool(record.get("IsRemovable")):
        return True

    friendly_name = str(record.get("FriendlyName", "")).strip()
    if bus_type == "SCSI" and _looks_like_scsi_card_reader(friendly_name):
        return True

    return False


def _map_disk_to_device_info(record: dict[str, Any]) -> DeviceInfo | None:
    try:
        disk_number = int(record["Number"])
        size_bytes = int(record["Size"])
    except (KeyError, TypeError, ValueError):
        return None

    if disk_number < 0 or size_bytes <= 0:
        return None

    friendly_name = str(record.get("FriendlyName") or f"Disk {disk_number}").strip()
    bus_type = str(record.get("BusType", "")).strip().upper()
    drive_letters = sorted(_normalize_drive_letters(record.get("DriveLetters")))

    detail_parts: list[str] = []
    if drive_letters:
        detail_parts.append("/".join(drive_letters))
    if bus_type:
        detail_parts.append(bus_type)

    suffix = f" ({', '.join(detail_parts)})" if detail_parts else ""

    return DeviceInfo(
        device_id=fr"\\.\PHYSICALDRIVE{disk_number}",
        display_name=f"{friendly_name}{suffix}",
        size_gb=max(1, size_bytes // (1024**3)),
        removable=True,
    )


def _parse_and_map_disks(json_output: str, app_path: Path | str | None) -> list[DeviceInfo]:
    if not json_output.strip():
        return []

    try:
        raw_data = json.loads(json_output)
    except json.JSONDecodeError:
        return []

    if isinstance(raw_data, dict):
        raw_records = [raw_data]
    elif isinstance(raw_data, list):
        raw_records = raw_data
    else:
        return []

    app_drive = _normalize_drive_root(app_path)
    devices: list[DeviceInfo] = []
    seen_device_ids: set[str] = set()

    for record in raw_records:
        if not isinstance(record, dict):
            continue

        if not _is_candidate_removable_disk(record):
            continue

        drive_letters = _normalize_drive_letters(record.get("DriveLetters"))
        if app_drive and app_drive in drive_letters:
            continue

        device = _map_disk_to_device_info(record)
        if device is None:
            continue

        if device.device_id in seen_device_ids:
            continue

        seen_device_ids.add(device.device_id)
        devices.append(device)

    return devices


def _run_windows_disk_query() -> str:
    if sys.platform != "win32":
        return ""

    powershell_script = r"""
$disks = Get-Disk | Where-Object {
    (-not $_.IsSystem) -and
    (-not $_.IsBoot)
}

$records = foreach ($disk in $disks) {
    $letters = @(
        Get-Partition -DiskNumber $disk.Number -ErrorAction SilentlyContinue |
        ForEach-Object {
            if ($_.DriveLetter) { "$($_.DriveLetter):" }
        }
    )

    [PSCustomObject]@{
        Number       = $disk.Number
        FriendlyName = $disk.FriendlyName
        Size         = $disk.Size
        BusType      = [string]$disk.BusType
        IsSystem     = [bool]$disk.IsSystem
        IsBoot       = [bool]$disk.IsBoot
        IsRemovable  = [bool]$disk.IsRemovable
        DriveLetters = @($letters)
    }
}

@($records) | ConvertTo-Json -Compress
""".strip()

    command = [
        "powershell.exe",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-Command",
        powershell_script,
    ]

    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return result.stdout.strip() or "[]"
    except (subprocess.CalledProcessError, FileNotFoundError, OSError) as exc:
        LOG.warning("Could not get Windows disk information: %s", exc)
        return ""


def get_windows_disks(app_path: Path | str | None = None) -> list[DeviceInfo]:
    json_output = _run_windows_disk_query()
    if not json_output:
        return []
    return _parse_and_map_disks(json_output, app_path)
