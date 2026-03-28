from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path
from typing import Callable

ProgressCallback = Callable[[int, int], None]
CancelCallback = Callable[[], bool]

_DEVICE_ID_PATTERN = re.compile(r"^\\\\\.\\PHYSICALDRIVE(\d+)$", re.IGNORECASE)


class CopyCancelledError(RuntimeError):
    pass


def _extract_disk_number(device_id: str) -> int | None:
    text = (device_id or "").strip()
    match = _DEVICE_ID_PATTERN.fullmatch(text)
    if not match:
        return None

    try:
        disk_number = int(match.group(1))
    except ValueError:
        return None

    if disk_number < 0:
        return None

    return disk_number


def get_physical_drive_size_bytes(device_id: str) -> int | None:
    if sys.platform != "win32":
        return None

    disk_number = _extract_disk_number(device_id)
    if disk_number is None:
        return None

    command = [
        "powershell.exe",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-Command",
        f"(Get-Disk -Number {disk_number} -ErrorAction Stop).Size",
    ]

    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (subprocess.CalledProcessError, FileNotFoundError, OSError):
        return None

    try:
        size_bytes = int(result.stdout.strip())
    except (TypeError, ValueError):
        return None

    if size_bytes <= 0:
        return None

    return size_bytes


def copy_physical_drive_to_image(
    device_id: str,
    output_path: Path,
    *,
    chunk_size: int = 8 * 1024 * 1024,
    progress_callback: ProgressCallback | None = None,
    cancel_callback: CancelCallback | None = None,
) -> int:
    if chunk_size <= 0:
        raise ValueError("chunk_size must be greater than zero")

    total_size = get_physical_drive_size_bytes(device_id)
    if total_size is None:
        raise RuntimeError("Could not determine the size of the selected device.")

    output_path.parent.mkdir(parents=True, exist_ok=True)

    bytes_copied = 0
    with open(device_id, "rb", buffering=0) as source_handle, output_path.open("wb") as target_handle:
        while bytes_copied < total_size:
            if cancel_callback is not None and cancel_callback():
                raise CopyCancelledError("Copy cancelled.")

            bytes_remaining = total_size - bytes_copied
            bytes_to_read = min(chunk_size, bytes_remaining)

            chunk = source_handle.read(bytes_to_read)
            if not chunk:
                raise OSError("Unexpected end of device while reading raw data.")

            target_handle.write(chunk)
            bytes_copied += len(chunk)

            if progress_callback is not None:
                progress_callback(bytes_copied, total_size)

    return bytes_copied


def copy_image_to_physical_drive(
    image_path: Path,
    device_id: str,
    *,
    chunk_size: int = 8 * 1024 * 1024,
    progress_callback: ProgressCallback | None = None,
    cancel_callback: CancelCallback | None = None,
) -> int:
    if chunk_size <= 0:
        raise ValueError("chunk_size must be greater than zero")

    if not image_path.exists() or not image_path.is_file():
        raise RuntimeError("The selected image file does not exist or is not a normal file.")

    total_size = image_path.stat().st_size
    if total_size <= 0:
        raise RuntimeError("The selected image file is empty.")

    device_size = get_physical_drive_size_bytes(device_id)
    if device_size is None:
        raise RuntimeError("Could not determine the size of the selected device.")

    if total_size > device_size:
        raise RuntimeError("The selected image is larger than the target device.")

    bytes_written = 0
    with image_path.open("rb") as source_handle, open(device_id, "wb", buffering=0) as target_handle:
        while True:
            if cancel_callback is not None and cancel_callback():
                raise CopyCancelledError("Copy cancelled.")

            chunk = source_handle.read(chunk_size)
            if not chunk:
                break

            target_handle.write(chunk)
            bytes_written += len(chunk)

            if progress_callback is not None:
                progress_callback(bytes_written, total_size)

    return bytes_written
