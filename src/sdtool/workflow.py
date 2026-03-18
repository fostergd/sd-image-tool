from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class StepStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETE = "complete"
    FAILED = "failed"


@dataclass(slots=True)
class WorkflowStep:
    name: str
    detail: str
    status: StepStatus = StepStatus.PENDING


class WorkflowController:
    def __init__(self) -> None:
        self.operation_name: str | None = None
        self.steps: list[WorkflowStep] = []

    def start_operation(self, operation_name: str, step_definitions: list[tuple[str, str]]) -> None:
        self.operation_name = operation_name
        self.steps = [WorkflowStep(name=name, detail=detail) for name, detail in step_definitions]
        if self.steps:
            self.steps[0].status = StepStatus.RUNNING

    def set_running_step(self, step_index: int) -> None:
        if not self.steps:
            return

        step_index = max(0, min(step_index, len(self.steps) - 1))

        for idx, step in enumerate(self.steps):
            if idx < step_index:
                step.status = StepStatus.COMPLETE
            elif idx == step_index:
                step.status = StepStatus.RUNNING
            else:
                step.status = StepStatus.PENDING

    def apply_progress(self, percent: int) -> None:
        if not self.steps:
            return

        percent = max(0, min(100, percent))
        if percent >= 100:
            self.complete_operation()
            return

        total = len(self.steps)
        current_index = min(total - 1, int((percent / 100) * total))

        for idx, step in enumerate(self.steps):
            if idx < current_index:
                step.status = StepStatus.COMPLETE
            elif idx == current_index:
                step.status = StepStatus.RUNNING
            else:
                step.status = StepStatus.PENDING

    def complete_operation(self) -> None:
        for step in self.steps:
            step.status = StepStatus.COMPLETE

    def fail_operation(self) -> None:
        for step in self.steps:
            if step.status == StepStatus.RUNNING:
                step.status = StepStatus.FAILED
                return

        if self.steps:
            self.steps[-1].status = StepStatus.FAILED

    def reset(self) -> None:
        self.operation_name = None
        self.steps = []