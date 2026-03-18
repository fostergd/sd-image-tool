from __future__ import annotations

from datetime import datetime
from pathlib import Path
import subprocess

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from sdtool.backend import BackendInterface, MockBackend, OperationContext
from sdtool.workflow import StepStatus, WorkflowController
from sdtool.wsl_shrink import (
    WslCommandPlan,
    build_pishrink_plan,
    check_wsl_pishrink_available,
    start_pishrink_process,
)


class MainWindow(QMainWindow):
    def __init__(self, backend: BackendInterface | None = None) -> None:
        super().__init__()
        self.setWindowTitle("SD Image Tool - Mock Backend")
        self.resize(1200, 760)

        self.backend = backend or MockBackend()
        self.controller = WorkflowController()
        self.active_operation: str | None = None
        self.active_context: OperationContext | None = None
        self.active_source_label = ""
        self.active_target_label = ""
        self.progress_value = 0

        self.timer = QTimer(self)
        self.timer.setInterval(120)
        self.timer.timeout.connect(self._advance_mock_operation)

        self.shrink_poll_timer = QTimer(self)
        self.shrink_poll_timer.setInterval(500)
        self.shrink_poll_timer.timeout.connect(self._poll_shrink_process)

        self.active_shrink_process: subprocess.Popen[str] | None = None
        self.active_shrink_plan: WslCommandPlan | None = None
        self.shrink_progress_value = 0

        self._build_ui()
        self._load_devices()
        self._log("Mock backend is enabled for save/write/verify. Shrink can run in real WSL mode.")
        self._set_status("Ready. Safe mock backend active.")

    def _build_ui(self) -> None:
        central = QWidget(self)
        self.setCentralWidget(central)

        root = QVBoxLayout(central)
        root.setSpacing(12)

        top_notice = QLabel(
            "This build is intentionally non-destructive for disk access. "
            "Save, Write, and Verify are mocked. Shrink can run through WSL PiShrink."
        )
        top_notice.setWordWrap(True)
        root.addWidget(top_notice)

        controls_layout = QHBoxLayout()
        controls_layout.addWidget(self._build_sources_group(), 1)
        controls_layout.addWidget(self._build_actions_group(), 1)
        root.addLayout(controls_layout)

        progress_group = QGroupBox("Current Status")
        progress_layout = QVBoxLayout(progress_group)

        self.status_label = QLabel("Ready.")
        progress_layout.addWidget(self.status_label)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        progress_layout.addWidget(self.progress_bar)

        root.addWidget(progress_group)

        bottom_layout = QHBoxLayout()
        bottom_layout.addWidget(self._build_queue_group(), 1)
        bottom_layout.addWidget(self._build_recent_jobs_group(), 1)
        bottom_layout.addWidget(self._build_log_group(), 2)
        root.addLayout(bottom_layout, 1)

    def _build_sources_group(self) -> QGroupBox:
        group = QGroupBox("Sources / Targets / Files")
        layout = QGridLayout(group)

        layout.addWidget(QLabel("Source SD/Card Reader"), 0, 0)
        self.source_combo = QComboBox()
        layout.addWidget(self.source_combo, 0, 1)

        layout.addWidget(QLabel("Target SD/Card Reader"), 1, 0)
        self.target_combo = QComboBox()
        layout.addWidget(self.target_combo, 1, 1)

        layout.addWidget(QLabel("Image File"), 2, 0)
        self.image_path_edit = QLineEdit(str(Path.home() / "sd-images" / "raspi-image.img"))
        layout.addWidget(self.image_path_edit, 2, 1)

        browse_btn = QPushButton("Browse...")
        browse_btn.clicked.connect(self._browse_image_path)
        layout.addWidget(browse_btn, 2, 2)

        refresh_btn = QPushButton("Refresh Device List")
        refresh_btn.clicked.connect(self._load_devices)
        layout.addWidget(refresh_btn, 3, 1)

        return group

    def _build_actions_group(self) -> QGroupBox:
        group = QGroupBox("Actions")
        layout = QVBoxLayout(group)

        self.save_btn = QPushButton("Save SD Card to Image")
        self.save_btn.clicked.connect(lambda: self._start_operation("save"))
        layout.addWidget(self.save_btn)

        self.shrink_btn = QPushButton("Shrink Existing Image")
        self.shrink_btn.clicked.connect(lambda: self._start_operation("shrink"))
        layout.addWidget(self.shrink_btn)

        self.write_btn = QPushButton("Write Image to SD Card")
        self.write_btn.clicked.connect(lambda: self._start_operation("write"))
        layout.addWidget(self.write_btn)

        self.verify_btn = QPushButton("Verify Last Write")
        self.verify_btn.clicked.connect(lambda: self._start_operation("verify"))
        layout.addWidget(self.verify_btn)

        self.cancel_btn = QPushButton("Cancel Current Task")
        self.cancel_btn.clicked.connect(self._cancel_operation)
        layout.addWidget(self.cancel_btn)

        layout.addStretch(1)
        return group

    def _build_queue_group(self) -> QGroupBox:
        group = QGroupBox("Planned / Running Steps")
        layout = QVBoxLayout(group)
        self.queue_list = QListWidget()
        layout.addWidget(self.queue_list)
        return group

    def _build_recent_jobs_group(self) -> QGroupBox:
        group = QGroupBox("Recent Jobs")
        layout = QVBoxLayout(group)

        help_label = QLabel(
            "Completed and cancelled operations appear here with the device selections and image path used."
        )
        help_label.setWordWrap(True)
        layout.addWidget(help_label)

        self.recent_jobs_list = QListWidget()
        layout.addWidget(self.recent_jobs_list)

        return group

    def _build_log_group(self) -> QGroupBox:
        group = QGroupBox("Activity Log")
        layout = QVBoxLayout(group)
        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        layout.addWidget(self.log_view)
        return group

    def _browse_image_path(self) -> None:
        filename, _ = QFileDialog.getOpenFileName(
            self,
            "Choose image file",
            self.image_path_edit.text(),
            "Image Files (*.img);;All Files (*.*)",
        )
        if filename:
            self.image_path_edit.setText(filename)
            self._log(f"Selected image path: {filename}")

    def _load_devices(self) -> None:
        source_devices = self.backend.list_source_devices()
        target_devices = self.backend.list_target_devices()

        self.source_combo.clear()
        for device in source_devices:
            self.source_combo.addItem(device.label(), device.device_id)

        self.target_combo.clear()
        for device in target_devices:
            self.target_combo.addItem(device.label(), device.device_id)

        self._log("Refreshed device list from backend.")
        self._set_status("Device list refreshed.")

    def _start_operation(self, operation_name: str) -> None:
        if self.timer.isActive() or self.shrink_poll_timer.isActive():
            QMessageBox.information(
                self,
                "Operation already running",
                "A task is already in progress. Cancel it first if you want to switch tasks.",
            )
            return

        context = OperationContext(
            operation_name=operation_name,
            source_device_id=self.source_combo.currentData(),
            target_device_id=self.target_combo.currentData(),
            image_path=self.image_path_edit.text().strip(),
        )

        if operation_name == "shrink":
            self._start_real_shrink_operation(context)
            return

        self._start_mock_operation(context)

    def _start_mock_operation(self, context: OperationContext) -> None:
        warnings = self.backend.validate_operation(context)
        if warnings:
            QMessageBox.warning(self, "Cannot start operation", "\n".join(warnings))
            self._log(f"Operation '{context.operation_name}' was blocked by validation.")
            return

        try:
            step_definitions = self.backend.get_operation_steps(context.operation_name)
        except ValueError as exc:
            QMessageBox.critical(self, "Unknown operation", str(exc))
            self._log(str(exc))
            return

        self.controller.start_operation(context.operation_name, step_definitions)
        self.active_operation = context.operation_name
        self.active_context = context
        self.active_source_label = self.source_combo.currentText()
        self.active_target_label = self.target_combo.currentText()
        self.progress_value = 1
        self.progress_bar.setValue(0)
        self._refresh_queue()

        self._log(
            f"Started mock '{context.operation_name}' operation. "
            f"Source={context.source_device_id} "
            f"Target={context.target_device_id} "
            f"Image={context.image_path}"
        )
        self._set_status(f"Running '{context.operation_name}' operation...")
        self.timer.start()

    def _start_real_shrink_operation(self, context: OperationContext) -> None:
        warnings = self.backend.validate_operation(context)
        if warnings:
            QMessageBox.warning(self, "Cannot start operation", "\n".join(warnings))
            self._log("Shrink operation was blocked by validation.")
            return

        image_path = Path(context.image_path)
        if not image_path.is_absolute():
            QMessageBox.warning(
                self,
                "Absolute image path required",
                "Shrink requires a full Windows path such as D:\\images\\raspios.img.",
            )
            self._log("Shrink blocked because the image path was not absolute.")
            return

        if not image_path.exists() or not image_path.is_file():
            QMessageBox.warning(
                self,
                "Image file not found",
                "The selected image file does not exist or is not a normal file.",
            )
            self._log(f"Shrink blocked because the image file was not found: {context.image_path}")
            return

        if not check_wsl_pishrink_available():
            QMessageBox.critical(
                self,
                "PiShrink not available",
                "WSL PiShrink was not found. Confirm that WSL Ubuntu and pishrink.sh are installed.",
            )
            self._log("Shrink blocked because WSL PiShrink was not available.")
            return

        try:
            plan = build_pishrink_plan(context.image_path)
            step_definitions = self.backend.get_operation_steps("shrink")
        except ValueError as exc:
            QMessageBox.critical(self, "Cannot prepare shrink", str(exc))
            self._log(f"Shrink preparation failed: {exc}")
            return

        self.controller.start_operation("shrink", step_definitions)
        self.controller.set_running_step(1)
        self.active_operation = "shrink"
        self.active_context = context
        self.active_source_label = self.source_combo.currentText()
        self.active_target_label = self.target_combo.currentText()
        self.active_shrink_plan = plan
        self.shrink_progress_value = 15
        self.progress_bar.setValue(self.shrink_progress_value)
        self._refresh_queue()

        self._log(f"Prepared WSL shrink plan for: {plan.image_path_windows}")
        self._log(f"Shrink output will be: {plan.output_path_windows}")
        self._log(f"WSL command: {plan.shell_command}")
        self._set_status("Starting WSL shrink. This may take a while for large images...")

        self.active_shrink_process = start_pishrink_process(plan)
        self.controller.set_running_step(2)
        self.shrink_progress_value = 30
        self.progress_bar.setValue(self.shrink_progress_value)
        self._refresh_queue()
        self.shrink_poll_timer.start()

    def _advance_mock_operation(self) -> None:
        self.progress_value += 4
        if self.progress_value >= 100:
            self.progress_value = 100
            self.controller.complete_operation()
            self.timer.stop()
            completed_name = self.active_operation or "operation"
            self._refresh_queue()
            self.progress_bar.setValue(100)
            self._set_status(f"Completed '{completed_name}' in mock backend.")
            self._log(f"Completed mock '{completed_name}' operation.")
            self._record_recent_job("Completed", completed_name)
            self._clear_active_operation_state()
            return

        self.controller.apply_progress(self.progress_value)
        self.progress_bar.setValue(self.progress_value)
        self._refresh_queue()
        self._set_status(f"Running '{self.active_operation}' operation... {self.progress_value}%")

    def _poll_shrink_process(self) -> None:
        if self.active_shrink_process is None:
            self.shrink_poll_timer.stop()
            return

        returncode = self.active_shrink_process.poll()
        if returncode is None:
            self.shrink_progress_value = min(90, self.shrink_progress_value + 3)
            self.controller.set_running_step(2)
            self.progress_bar.setValue(self.shrink_progress_value)
            self._refresh_queue()
            self._set_status(
                f"Shrinking image in WSL... {self.shrink_progress_value}% "
                f"(large images can take quite a while)"
            )
            return

        self.shrink_poll_timer.stop()
        stdout, stderr = self.active_shrink_process.communicate()
        plan = self.active_shrink_plan
        completed_name = self.active_operation or "shrink"

        if returncode == 0:
            self.controller.set_running_step(3)
            self.progress_bar.setValue(95)
            self._refresh_queue()
            self.controller.complete_operation()
            self.progress_bar.setValue(100)
            self._refresh_queue()
            self._set_status("Shrink completed successfully.")
            self._log(f"Completed real WSL shrink operation: {completed_name}")
            if plan is not None:
                self._log(f"Shrink output image: {plan.output_path_windows}")
            if stdout.strip():
                self._log("PiShrink output:")
                self._log(stdout.strip())
            self._record_recent_job("Completed", completed_name)
        else:
            self.controller.fail_operation()
            self._refresh_queue()
            self._set_status("Shrink failed.")
            self._log(f"WSL shrink failed with return code {returncode}.")
            if stderr.strip():
                self._log("PiShrink error output:")
                self._log(stderr.strip())
            if stdout.strip():
                self._log("PiShrink standard output:")
                self._log(stdout.strip())
            self._record_recent_job("Failed", completed_name)
            QMessageBox.critical(
                self,
                "Shrink failed",
                "PiShrink reported an error. Review the Activity Log for details.",
            )

        self._clear_active_operation_state()

    def _cancel_operation(self) -> None:
        if self.timer.isActive():
            self.timer.stop()
            failed_name = self.active_operation or "operation"
            self.controller.fail_operation()
            self._refresh_queue()
            self._set_status(f"Cancelled '{failed_name}'.")
            self._log(f"Cancelled mock '{failed_name}' operation.")
            self.progress_bar.setValue(0)
            self._record_recent_job("Cancelled", failed_name)
            self._clear_active_operation_state()
            return

        if self.shrink_poll_timer.isActive() and self.active_shrink_process is not None:
            self.shrink_poll_timer.stop()
            failed_name = self.active_operation or "shrink"
            self._log("Cancellation requested for WSL shrink process.")
            self.active_shrink_process.terminate()

            try:
                stdout, stderr = self.active_shrink_process.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                self.active_shrink_process.kill()
                stdout, stderr = self.active_shrink_process.communicate()

            self.controller.fail_operation()
            self._refresh_queue()
            self._set_status(f"Cancelled '{failed_name}'.")
            self._log(f"Cancelled real WSL shrink operation: {failed_name}")
            if stdout.strip():
                self._log("Process output before cancellation:")
                self._log(stdout.strip())
            if stderr.strip():
                self._log("Process errors before cancellation:")
                self._log(stderr.strip())
            self.progress_bar.setValue(0)
            self._record_recent_job("Cancelled", failed_name)
            self._clear_active_operation_state()
            return

        self._log("Cancel requested, but no operation was active.")
        self._set_status("No active operation to cancel.")

    def _record_recent_job(self, status: str, operation_name: str) -> None:
        if self.active_context is None:
            return

        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        image_path = self.active_context.image_path or "(none)"
        display_text = (
            f"{timestamp} | {status} | {operation_name} | "
            f"Source: {self.active_source_label or '(none)'} | "
            f"Target: {self.active_target_label or '(none)'}"
        )

        item = QListWidgetItem(display_text)
        item.setToolTip(
            f"Time: {timestamp}\n"
            f"Status: {status}\n"
            f"Operation: {operation_name}\n"
            f"Source: {self.active_source_label or '(none)'}\n"
            f"Target: {self.active_target_label or '(none)'}\n"
            f"Image: {image_path}"
        )
        self.recent_jobs_list.insertItem(0, item)

        while self.recent_jobs_list.count() > 50:
            self.recent_jobs_list.takeItem(self.recent_jobs_list.count() - 1)

        self._log(
            f"Recent job recorded: {status} {operation_name} | "
            f"Source={self.active_source_label or '(none)'} | "
            f"Target={self.active_target_label or '(none)'} | "
            f"Image={image_path}"
        )

    def _clear_active_operation_state(self) -> None:
        self.active_operation = None
        self.active_context = None
        self.active_source_label = ""
        self.active_target_label = ""
        self.active_shrink_process = None
        self.active_shrink_plan = None
        self.progress_value = 0
        self.shrink_progress_value = 0

    def _refresh_queue(self) -> None:
        icons = {
            StepStatus.PENDING: "○",
            StepStatus.RUNNING: "▶",
            StepStatus.COMPLETE: "✓",
            StepStatus.FAILED: "✗",
        }

        self.queue_list.clear()
        for step in self.controller.steps:
            icon = icons[step.status]
            item = QListWidgetItem(f"{icon} {step.name} — {step.detail}")
            self.queue_list.addItem(item)

    def _set_status(self, message: str) -> None:
        self.status_label.setText(message)

    def _log(self, message: str) -> None:
        self.log_view.append(message)