from __future__ import annotations

from pathlib import Path

import pytest

import sdtool.windows_raw as windows_raw
from sdtool.windows_raw import (
    CopyCancelledError,
    _extract_disk_number,
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
