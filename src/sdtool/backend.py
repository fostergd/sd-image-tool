from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

from sdtool.models import DeviceInfo, mock_source_devices, mock_target_devices
from sdtool.windows_disks import get_windows_disks

OperationSteps = list[tuple[str, str]]

DEFAULT_OPERATION_STEPS: dict[str, OperationSteps] = {
    "save": [
        ("Check source device", "Confirm selected SD card is removable and readable."),
        ("Read card to image", "Copy raw device contents to an image file."),
        ("Validate image", "Confirm image size and basic integrity checks."),
        ("Finish", "Present summary and next available action."),
    ],
    "shrink": [
        ("Validate image", "Confirm the selected image exists and is readable."),
        ("Send to WSL", "Hand off the image to the Linux shrink backend."),
        ("Run PiShrink", "Shrink the filesystem and image size."),
        ("Verify output", "Check that the shrunken image was produced."),
    ],
    "write": [
        ("Check target device", "Confirm selected target is removable and large enough."),
        ("Write image", "Copy the image file to the selected target device."),
        ("Verify write", "Perform a post-write verification pass."),
        ("Finish", "Present summary and next available action."),
    ],
    "verify": [
        ("Read sample blocks", "Collect source and target sample data."),
        ("Compare", "Compare samples or checksums."),
        ("Finish", "Present verification result."),
    ],
}


@dataclass(slots=True, frozen=True)
class OperationContext:
    operation_name: str
    source_device_id: str | None = None
    target_device_id: str | None = None
    image_path: str = ""


class BackendInterface(ABC):
    @abstractmethod
    def list_source_devices(self) -> list[DeviceInfo]:
        raise NotImplementedError

    @abstractmethod
    def list_target_devices(self) -> list[DeviceInfo]:
        raise NotImplementedError

    @abstractmethod
    def get_operation_steps(self, operation_name: str) -> OperationSteps:
        raise NotImplementedError

    def validate_operation(self, context: OperationContext) -> list[str]:
        return []


class MockBackend(BackendInterface):
    def __init__(self, operation_steps: dict[str, OperationSteps] | None = None) -> None:
        self._operation_steps = operation_steps or DEFAULT_OPERATION_STEPS

    def _discover_windows_removable_disks(self) -> list[DeviceInfo]:
        try:
            return get_windows_disks(Path(__file__).resolve())
        except Exception:
            return []

    def list_source_devices(self) -> list[DeviceInfo]:
        discovered = self._discover_windows_removable_disks()
        return discovered or mock_source_devices()

    def list_target_devices(self) -> list[DeviceInfo]:
        discovered = self._discover_windows_removable_disks()
        return discovered or mock_target_devices()

    def get_operation_steps(self, operation_name: str) -> OperationSteps:
        try:
            return list(self._operation_steps[operation_name])
        except KeyError as exc:
            raise ValueError(f"Unknown operation: {operation_name}") from exc

    def validate_operation(self, context: OperationContext) -> list[str]:
        warnings: list[str] = []

        if context.operation_name in {"save", "shrink", "write"} and not context.image_path.strip():
            warnings.append("An image path is required for this operation.")

        if context.source_device_id and context.source_device_id == context.target_device_id:
            warnings.append("Source and target devices cannot be the same.")

        return warnings
