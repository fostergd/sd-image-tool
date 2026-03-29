from __future__ import annotations

import ctypes
import re
import subprocess
import sys
from contextlib import contextmanager
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


def _is_windows_physical_drive(device_id: str) -> bool:
    return sys.platform == "win32" and _extract_disk_number(device_id) is not None


if sys.platform == "win32":
    from ctypes import wintypes

    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    _CreateFileW = _kernel32.CreateFileW
    _CreateFileW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    _CreateFileW.restype = wintypes.HANDLE

    _WriteFile = _kernel32.WriteFile
    _WriteFile.argtypes = [
        wintypes.HANDLE,
        wintypes.LPCVOID,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
        wintypes.LPVOID,
    ]
    _WriteFile.restype = wintypes.BOOL

    _CloseHandle = _kernel32.CloseHandle
    _CloseHandle.argtypes = [wintypes.HANDLE]
    _CloseHandle.restype = wintypes.BOOL

    _SetFilePointerEx = _kernel32.SetFilePointerEx
    _SetFilePointerEx.argtypes = [
        wintypes.HANDLE,
        ctypes.c_longlong,
        ctypes.POINTER(ctypes.c_longlong),
        wintypes.DWORD,
    ]
    _SetFilePointerEx.restype = wintypes.BOOL

    _DeviceIoControl = _kernel32.DeviceIoControl
    _DeviceIoControl.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
        wintypes.LPVOID,
    ]
    _DeviceIoControl.restype = wintypes.BOOL

    GENERIC_READ = 0x80000000
    GENERIC_WRITE = 0x40000000
    FILE_SHARE_READ = 0x00000001
    FILE_SHARE_WRITE = 0x00000002
    OPEN_EXISTING = 3
    FILE_ATTRIBUTE_NORMAL = 0x00000080
    FILE_BEGIN = 0

    FSCTL_LOCK_VOLUME = 0x00090018
    FSCTL_UNLOCK_VOLUME = 0x0009001C
    FSCTL_DISMOUNT_VOLUME = 0x00090020

    INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
else:
    _kernel32 = None


def _raise_last_windows_error(prefix: str) -> None:
    code = ctypes.get_last_error()
    message = ctypes.FormatError(code).strip()
    raise OSError(code, f"{prefix}: {message}")


def _open_windows_physical_drive_for_write(device_id: str):
    handle = _CreateFileW(
        device_id,
        GENERIC_READ | GENERIC_WRITE,
        FILE_SHARE_READ | FILE_SHARE_WRITE,
        None,
        OPEN_EXISTING,
        FILE_ATTRIBUTE_NORMAL,
        None,
    )
    if handle == INVALID_HANDLE_VALUE:
        _raise_last_windows_error(f"Could not open target device {device_id}")
    return handle


def _open_windows_volume_for_direct_access(volume_path: str):
    handle = _CreateFileW(
        volume_path,
        GENERIC_READ | GENERIC_WRITE,
        FILE_SHARE_READ | FILE_SHARE_WRITE,
        None,
        OPEN_EXISTING,
        FILE_ATTRIBUTE_NORMAL,
        None,
    )
    if handle == INVALID_HANDLE_VALUE:
        _raise_last_windows_error(f"Could not open mounted volume {volume_path}")
    return handle


def _seek_windows_handle_to_start(handle) -> None:
    new_pos = ctypes.c_longlong(0)
    ok = _SetFilePointerEx(handle, 0, ctypes.byref(new_pos), FILE_BEGIN)
    if not ok:
        _raise_last_windows_error("Could not seek target device to offset 0")


def _device_io_control_no_buffer(handle, control_code: int, prefix: str) -> None:
    bytes_returned = wintypes.DWORD(0)
    ok = _DeviceIoControl(
        handle,
        control_code,
        None,
        0,
        None,
        0,
        ctypes.byref(bytes_returned),
        None,
    )
    if not ok:
        _raise_last_windows_error(prefix)


def _write_chunk_to_windows_handle(handle, chunk: bytes) -> None:
    if not chunk:
        return

    offset = 0
    total = len(chunk)

    while offset < total:
        remaining = total - offset
        view = chunk[offset:]
        buffer = (ctypes.c_char * remaining).from_buffer_copy(view)
        written = wintypes.DWORD(0)

        ok = _WriteFile(
            handle,
            ctypes.byref(buffer),
            remaining,
            ctypes.byref(written),
            None,
        )
        if not ok:
            _raise_last_windows_error("WriteFile failed while writing to target device")

        if written.value <= 0:
            raise OSError("WriteFile returned success but wrote zero bytes.")

        offset += written.value


def _get_disk_drive_letters(device_id: str) -> list[str]:
    disk_number = _extract_disk_number(device_id)
    if disk_number is None or sys.platform != "win32":
        return []

    command = [
        "powershell.exe",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-Command",
        (
            f"Get-Partition -DiskNumber {disk_number} -ErrorAction SilentlyContinue | "
            "Where-Object DriveLetter | "
            "Select-Object -ExpandProperty DriveLetter"
        ),
    ]

    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (FileNotFoundError, OSError):
        return []

    if result.returncode != 0:
        return []

    letters: list[str] = []
    for line in result.stdout.splitlines():
        letter = line.strip().upper().rstrip(":")
        if len(letter) == 1 and letter.isalpha() and letter not in letters:
            letters.append(letter)

    return letters


@contextmanager
def _locked_dismounted_windows_volumes_for_disk(device_id: str):
    handles: list[tuple[object, str]] = []

    if not _is_windows_physical_drive(device_id):
        yield
        return

    drive_letters = _get_disk_drive_letters(device_id)

    try:
        for letter in drive_letters:
            volume_path = rf"\\.\{letter}:"
            handle = _open_windows_volume_for_direct_access(volume_path)
            try:
                _device_io_control_no_buffer(
                    handle,
                    FSCTL_LOCK_VOLUME,
                    (
                        f"Could not lock mounted volume {volume_path}. "
                        "Close any Explorer windows or apps using the SD card and try again"
                    ),
                )
                _device_io_control_no_buffer(
                    handle,
                    FSCTL_DISMOUNT_VOLUME,
                    f"Could not dismount mounted volume {volume_path}",
                )
            except Exception:
                _CloseHandle(handle)
                raise

            handles.append((handle, volume_path))

        yield
    finally:
        for handle, volume_path in reversed(handles):
            try:
                _device_io_control_no_buffer(
                    handle,
                    FSCTL_UNLOCK_VOLUME,
                    f"Could not unlock mounted volume {volume_path}",
                )
            except Exception:
                pass
            _CloseHandle(handle)


def _copy_image_to_windows_physical_drive(
    image_path: Path,
    device_id: str,
    *,
    chunk_size: int,
    progress_callback: ProgressCallback | None,
    cancel_callback: CancelCallback | None,
) -> int:
    total_size = image_path.stat().st_size
    bytes_written = 0

    with _locked_dismounted_windows_volumes_for_disk(device_id):
        handle = _open_windows_physical_drive_for_write(device_id)

        try:
            _seek_windows_handle_to_start(handle)

            with image_path.open("rb") as source_handle:
                while True:
                    if cancel_callback is not None and cancel_callback():
                        raise CopyCancelledError("Copy cancelled.")

                    chunk = source_handle.read(chunk_size)
                    if not chunk:
                        break

                    _write_chunk_to_windows_handle(handle, chunk)
                    bytes_written += len(chunk)

                    if progress_callback is not None:
                        progress_callback(bytes_written, total_size)
        finally:
            _CloseHandle(handle)

    return bytes_written


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

    if _is_windows_physical_drive(device_id):
        return _copy_image_to_windows_physical_drive(
            image_path,
            device_id,
            chunk_size=chunk_size,
            progress_callback=progress_callback,
            cancel_callback=cancel_callback,
        )

    bytes_written = 0
    with image_path.open("rb") as source_handle, open(device_id, "r+b", buffering=0) as target_handle:
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


def compare_image_to_physical_drive(
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

    bytes_verified = 0
    with image_path.open("rb") as image_handle, open(device_id, "rb", buffering=0) as device_handle:
        while bytes_verified < total_size:
            if cancel_callback is not None and cancel_callback():
                raise CopyCancelledError("Copy cancelled.")

            bytes_remaining = total_size - bytes_verified
            bytes_to_read = min(chunk_size, bytes_remaining)

            image_chunk = image_handle.read(bytes_to_read)
            if not image_chunk:
                break

            device_chunk = device_handle.read(len(image_chunk))
            if len(device_chunk) != len(image_chunk):
                raise OSError("Unexpected end of device while reading raw data for verification.")

            if image_chunk != device_chunk:
                for index, (image_byte, device_byte) in enumerate(zip(image_chunk, device_chunk)):
                    if image_byte != device_byte:
                        raise RuntimeError(
                            f"Verification failed: image and target device differ at byte offset {bytes_verified + index}."
                        )
                raise RuntimeError("Verification failed: image and target device differ.")

            bytes_verified += len(image_chunk)

            if progress_callback is not None:
                progress_callback(bytes_verified, total_size)

    return bytes_verified
