from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True, frozen=True)
class DeviceInfo:
    device_id: str
    display_name: str
    size_gb: int
    removable: bool = True

    def label(self) -> str:
        kind = "Removable" if self.removable else "Fixed"
        return f"{self.display_name} ({self.size_gb} GB, {kind})"


def mock_source_devices() -> list[DeviceInfo]:
    return [
        DeviceInfo(device_id="PHYSICALDRIVE2", display_name="USB SD Reader - Source", size_gb=64),
        DeviceInfo(device_id="PHYSICALDRIVE3", display_name="Internal SD Reader - Source", size_gb=32),
    ]


def mock_target_devices() -> list[DeviceInfo]:
    return [
        DeviceInfo(device_id="PHYSICALDRIVE4", display_name="USB SD Reader - Target", size_gb=64),
        DeviceInfo(device_id="PHYSICALDRIVE5", display_name="USB SD Reader - Target", size_gb=128),
    ]