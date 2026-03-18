from __future__ import annotations


def format_bytes(num_bytes: int) -> str:
    if num_bytes < 0:
        raise ValueError("Byte count cannot be negative.")

    units = ["B", "KB", "MB", "GB", "TB"]
    value = float(num_bytes)

    for unit in units:
        if value < 1024.0 or unit == units[-1]:
            if unit == "B":
                return f"{int(value)} {unit}"
            if value >= 10:
                return f"{value:.0f} {unit}"
            return f"{value:.1f} {unit}"
        value /= 1024.0

    return f"{num_bytes} B"


def describe_reduction(original_bytes: int, shrunk_bytes: int) -> str:
    if original_bytes <= 0:
        raise ValueError("Original size must be greater than zero.")
    if shrunk_bytes < 0:
        raise ValueError("Shrunk size cannot be negative.")
    if shrunk_bytes > original_bytes:
        raise ValueError("Shrunk size cannot exceed original size.")

    saved = original_bytes - shrunk_bytes
    percent = (saved / original_bytes) * 100.0
    return f"Saved {format_bytes(saved)} ({percent:.1f}%)"