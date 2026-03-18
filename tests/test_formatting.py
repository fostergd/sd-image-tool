import pytest

from sdtool.formatting import describe_reduction, format_bytes


def test_format_bytes_handles_bytes() -> None:
    assert format_bytes(512) == "512 B"


def test_format_bytes_handles_megabytes() -> None:
    assert format_bytes(5 * 1024 * 1024) == "5.0 MB"


def test_format_bytes_handles_gigabytes() -> None:
    assert format_bytes(5 * 1024 * 1024 * 1024) == "5.0 GB"


def test_describe_reduction_reports_saved_amount_and_percent() -> None:
    original = 10 * 1024 * 1024 * 1024
    shrunk = 6 * 1024 * 1024 * 1024

    result = describe_reduction(original, shrunk)

    assert result == "Saved 4.0 GB (40.0%)"


def test_describe_reduction_rejects_invalid_sizes() -> None:
    with pytest.raises(ValueError):
        describe_reduction(0, 0)

    with pytest.raises(ValueError):
        describe_reduction(100, 200)