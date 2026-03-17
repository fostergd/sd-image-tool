from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

@dataclass(slots=True)
class StepStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"

@dataclass(slots=True)
class WorkflowStep:
    name: str
    status: StepStatus = field(default=StepStatus.PENDING)

class BackendResponse:
    success: bool
    message: str

class BackendInterface:
    def __init__(self):
        pass

    def connect_to_windows_disk(self, device_id: str) -> BackendResponse:
        # Implement logic to connect to a Windows disk backend
        return BackendResponse(success=False, message="Windows disk connection failed")

    def shrink_wsl_image(self, image_path: str) -> BackendResponse:
        # Implement logic to shrink an WSL image using the WSL shrink tool
        return BackendResponse(success=False, message="WSL image shrinking failed")

class WorkflowController:
    def __init__(self):
        self.operation_name: str | None = None
        self.backend_interface = BackendInterface()
        self.steps: list[WorkflowStep] = []

    def start_operation(self, operation_name: str, step_definitions: list[tuple[str, str]]) -> None:
        self.operation_name = operation_name
        for name, backend in step_definitions:
            if backend == "windows_disk":
                response = self.backend_interface.connect_to_windows_disk(name)
                if not response.success:
                    self.fail_operation()
                    return
            elif backend == "wsl_shrink":
                response = self.backend_interface.shrink_wsl_image(name)
                if not response.success:
                    self.fail_operation()
                    return

    def apply_progress(self, percent: int) -> None:
        # Update progress logic here
        pass

    def complete_operation(self) -> None:
        # Complete operation logic here
        pass

    def fail_operation(self) -> None:
        # Fail operation logic here
        pass

    def reset(self) -> None:
        # Reset operation logic here
        pass
