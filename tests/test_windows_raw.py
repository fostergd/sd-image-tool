from __future__ import annotations

from sdtool.windows_raw import _extract_disk_number


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
