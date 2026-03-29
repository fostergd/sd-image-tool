from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

import sdtool.windows_raw as windows_raw
from sdtool.windows_raw import (
    CopyCancelledError,
    _extract_disk_number,
    compare_image_to_physical_drive,
    copy_image_to_physical_drive,
    copy_physical_drive_to_image,
)


def test_extract_disk_number_accepts_valid_device_id() -> None:
    assert _extract_disk_number(r"\\.\PHYSICALDRIVE0") == 0
    assert _extract_disk_number(r"\\.\PHYSICALDRIVE12") == 12


def test_extract_disk_number_is_case_insensitive() -> None:
    assert _extract_disk_number(r"\\.\physicaldrive7") == 7


def test_extract_disk_number_rejects_invalid_values() -> None:
    assert _extract_disk_number("") is None
    assert _extract_disk_number("PHYSICALDRIVE1") is None
    assert _extract_disk_number(r"\\.\C:") is None
    assert _extract_disk_number(r"\\.\PHYSICALDRIVEX") is None


def test_copy_physical_drive_to_image_reads_expected_bytes(tmp_path: Path, monkeypatch) -> None:
    fake_device = tmp_path / "fake-device.bin"
    fake_device.write_bytes(b"abcdefghij")
    output_path = tmp_path / "saved.img"

    monkeypatch.setattr(windows_raw, "get_physical_drive_size_bytes", lambda device_id: 10)

    progress_calls: list[tuple[int, int]] = []

    bytes_copied = copy_physical_drive_to_image(
        str(fake_device),
        output_path,
        chunk_size=4,
        progress_callback=lambda done, total: progress_calls.append((done, total)),
    )

    assert bytes_copied == 10
    assert output_path.read_bytes() == b"abcdefghij"
    assert progress_calls[-1] == (10, 10)


def test_copy_physical_drive_to_image_can_cancel(tmp_path: Path, monkeypatch) -> None:
    fake_device = tmp_path / "fake-device.bin"
    fake_device.write_bytes(b"abcdefghij")
    output_path = tmp_path / "saved.img"

    monkeypatch.setattr(windows_raw, "get_physical_drive_size_bytes", lambda device_id: 10)

    calls = {"count": 0}

    def cancel_callback() -> bool:
        calls["count"] += 1
        return calls["count"] > 1

    with pytest.raises(CopyCancelledError):
        copy_physical_drive_to_image(
            str(fake_device),
            output_path,
            chunk_size=4,
            cancel_callback=cancel_callback,
        )

    assert output_path.exists()
    assert len(output_path.read_bytes()) < 10


def test_copy_image_to_physical_drive_writes_expected_bytes(tmp_path: Path, monkeypatch) -> None:
    image_path = tmp_path / "input.img"
    image_path.write_bytes(b"1234567890")
    fake_device = tmp_path / "fake-device.bin"
    fake_device.write_bytes(b"\x00" * 10)

    monkeypatch.setattr(windows_raw, "get_physical_drive_size_bytes", lambda device_id: 10)

    progress_calls: list[tuple[int, int]] = []

    bytes_written = copy_image_to_physical_drive(
        image_path,
        str(fake_device),
        chunk_size=4,
        progress_callback=lambda done, total: progress_calls.append((done, total)),
    )

    assert bytes_written == 10
    assert fake_device.read_bytes() == b"1234567890"
    assert progress_calls[-1] == (10, 10)


def test_copy_image_to_physical_drive_rejects_oversized_image(tmp_path: Path, monkeypatch) -> None:
    image_path = tmp_path / "input.img"
    image_path.write_bytes(b"12345678901")
    fake_device = tmp_path / "fake-device.bin"
    fake_device.write_bytes(b"\x00" * 10)

    monkeypatch.setattr(windows_raw, "get_physical_drive_size_bytes", lambda device_id: 10)

    with pytest.raises(RuntimeError, match="larger than the target device"):
        copy_image_to_physical_drive(image_path, str(fake_device))


def test_copy_image_to_physical_drive_can_cancel(tmp_path: Path, monkeypatch) -> None:
    image_path = tmp_path / "input.img"
    image_path.write_bytes(b"abcdefghij")
    fake_device = tmp_path / "fake-device.bin"
    fake_device.write_bytes(b"\x00" * 10)

    monkeypatch.setattr(windows_raw, "get_physical_drive_size_bytes", lambda device_id: 10)

    calls = {"count": 0}

    def cancel_callback() -> bool:
        calls["count"] += 1
        return calls["count"] > 1

    with pytest.raises(CopyCancelledError):
        copy_image_to_physical_drive(
            image_path,
            str(fake_device),
            chunk_size=4,
            cancel_callback=cancel_callback,
        )

    assert fake_device.read_bytes()[:4] == b"abcd"


def test_compare_image_to_physical_drive_succeeds(tmp_path: Path, monkeypatch) -> None:
    image_path = tmp_path / "input.img"
    image_path.write_bytes(b"abcdefghij")
    fake_device = tmp_path / "fake-device.bin"
    fake_device.write_bytes(b"abcdefghij")

    monkeypatch.setattr(windows_raw, "get_physical_drive_size_bytes", lambda device_id: 10)

    progress_calls: list[tuple[int, int]] = []

    bytes_verified = compare_image_to_physical_drive(
        image_path,
        str(fake_device),
        chunk_size=4,
        progress_callback=lambda done, total: progress_calls.append((done, total)),
    )

    assert bytes_verified == 10
    assert progress_calls[-1] == (10, 10)


def test_compare_image_to_physical_drive_detects_mismatch(tmp_path: Path, monkeypatch) -> None:
    image_path = tmp_path / "input.img"
    image_path.write_bytes(b"abcdefghij")
    fake_device = tmp_path / "fake-device.bin"
    fake_device.write_bytes(b"abcdXfghij")

    monkeypatch.setattr(windows_raw, "get_physical_drive_size_bytes", lambda device_id: 10)

    with pytest.raises(RuntimeError, match="differ at byte offset 4"):
        compare_image_to_physical_drive(image_path, str(fake_device), chunk_size=4)


def test_compare_image_to_physical_drive_can_cancel(tmp_path: Path, monkeypatch) -> None:
    image_path = tmp_path / "input.img"
    image_path.write_bytes(b"abcdefghij")
    fake_device = tmp_path / "fake-device.bin"
    fake_device.write_bytes(b"abcdefghij")

    monkeypatch.setattr(windows_raw, "get_physical_drive_size_bytes", lambda device_id: 10)

    calls = {"count": 0}

    def cancel_callback() -> bool:
        calls["count"] += 1
        return calls["count"] > 1

    with pytest.raises(CopyCancelledError):
        compare_image_to_physical_drive(
            image_path,
            str(fake_device),
            chunk_size=4,
            cancel_callback=cancel_callback,
        )


def test_get_disk_drive_letters_parses_powershell_output(monkeypatch) -> None:
    monkeypatch.setattr(windows_raw.sys, "platform", "win32")

    def fake_run(command, capture_output, text, check, creationflags):
        return SimpleNamespace(returncode=0, stdout="F\nG\nF\n", stderr="")

    monkeypatch.setattr(windows_raw.subprocess, "run", fake_run)

    letters = windows_raw._get_disk_drive_letters(r"\\.\PHYSICALDRIVE2")

    assert letters == ["F", "G"]


def test_locked_dismounted_windows_volumes_for_disk_locks_and_unlocks(monkeypatch) -> None:
    monkeypatch.setattr(windows_raw, "_is_windows_physical_drive", lambda device_id: True)
    monkeypatch.setattr(windows_raw, "_get_disk_drive_letters", lambda device_id: ["F", "G"])

    opened: list[str] = []
    closed: list[str] = []
    io_calls: list[tuple[str, int]] = []

    def fake_open(volume_path: str):
        opened.append(volume_path)
        return volume_path

    def fake_ioctl(handle, code: int, prefix: str) -> None:
        io_calls.append((handle, code))

    monkeypatch.setattr(windows_raw, "_open_windows_volume_for_direct_access", fake_open)
    monkeypatch.setattr(windows_raw, "_device_io_control_no_buffer", fake_ioctl)
    monkeypatch.setattr(windows_raw, "_CloseHandle", lambda handle: closed.append(handle))

    with windows_raw._locked_dismounted_windows_volumes_for_disk(r"\\.\PHYSICALDRIVE2"):
        pass

    assert opened == [r"\\.\F:", r"\\.\G:"]
    assert io_calls == [
        (r"\\.\F:", windows_raw.FSCTL_LOCK_VOLUME),
        (r"\\.\F:", windows_raw.FSCTL_DISMOUNT_VOLUME),
        (r"\\.\G:", windows_raw.FSCTL_LOCK_VOLUME),
        (r"\\.\G:", windows_raw.FSCTL_DISMOUNT_VOLUME),
        (r"\\.\G:", windows_raw.FSCTL_UNLOCK_VOLUME),
        (r"\\.\F:", windows_raw.FSCTL_UNLOCK_VOLUME),
    ]
    assert closed == [r"\\.\G:", r"\\.\F:"]


def test_copy_image_to_physical_drive_uses_windows_physical_drive_path(tmp_path: Path, monkeypatch) -> None:
    image_path = tmp_path / "input.img"
    image_path.write_bytes(b"1234567890")

    monkeypatch.setattr(windows_raw, "get_physical_drive_size_bytes", lambda device_id: 10)
    monkeypatch.setattr(windows_raw, "_is_windows_physical_drive", lambda device_id: True)

    captured: dict[str, object] = {}

    def fake_copy(
        image_path_arg: Path,
        device_id_arg: str,
        *,
        chunk_size: int,
        progress_callback,
        cancel_callback,
    ) -> int:
        captured["image_path"] = image_path_arg
        captured["device_id"] = device_id_arg
        captured["chunk_size"] = chunk_size
        return 10

    monkeypatch.setattr(windows_raw, "_copy_image_to_windows_physical_drive", fake_copy)

    result = copy_image_to_physical_drive(image_path, r"\\.\PHYSICALDRIVE2")

    assert result == 10
    assert captured["image_path"] == image_path
    assert captured["device_id"] == r"\\.\PHYSICALDRIVE2"
