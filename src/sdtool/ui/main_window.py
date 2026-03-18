from __future__ import annotations

from datetime import datetime
from pathlib import Path

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

        self._build_ui()
        self._load_devices()
        self._log("Mock backend is enabled. No real disks are touched in this build.")
        self._set_status("Ready. Safe mock backend active.")

    def _build_ui(self) -> None:
        central = QWidget(self)
        self.setCentralWidget(central)

        root = QVBoxLayout(central)
        root.setSpacing(12)

        top_notice = QLabel(
            "This build is intentionally non-destructive. "
            "It lets us iterate on workflow, status reporting, and long-running operations safely."
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
        self.save_btn.clicked.connect(lambda: self._start_mock_operation("save"))
        layout.addWidget(self.save_btn)

        self.shrink_btn = QPushButton("Shrink Existing Image")
        self.shrink_btn.clicked.connect(lambda: self._start_mock_operation("shrink"))
        layout.addWidget(self.shrink_btn)

        self.write_btn = QPushButton("Write Image to SD Card")
        self.write_btn.clicked.connect(lambda: self._start_mock_operation("write"))
        layout.addWidget(self.write_btn)

        self.verify_btn = QPushButton("Verify Last Write")
        self.verify_btn.clicked.connect(lambda: self._start_mock_operation("verify"))
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
        filename, _ = QFileDialog.getSaveFileName(
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

    def _start_mock_operation(self, operation_name: str) -> None:
        if self.timer.isActive():
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

        warnings = self.backend.validate_operation(context)
        if warnings:
            QMessageBox.warning(self, "Cannot start operation", "\n".join(warnings))
            self._log(f"Operation '{operation_name}' was blocked by validation.")
            return

        try:
            step_definitions = self.backend.get_operation_steps(operation_name)
        except ValueError as exc:
            QMessageBox.critical(self, "Unknown operation", str(exc))
            self._log(str(exc))
            return

        self.controller.start_operation(operation_name, step_definitions)
        self.active_operation = operation_name
        self.active_context = context
        self.active_source_label = self.source_combo.currentText()
        self.active_target_label = self.target_combo.currentText()
        self.progress_value = 1
        self.progress_bar.setValue(0)
        self._refresh_queue()

        self._log(
            f"Started mock '{operation_name}' operation. "
            f"Source={context.source_device_id} "
            f"Target={context.target_device_id} "
            f"Image={context.image_path}"
        )
        self._set_status(f"Running '{operation_name}' operation...")
        self.timer.start()

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
            self.active_operation = None
            self.active_context = None
            self.active_source_label = ""
            self.active_target_label = ""
            return

        self.controller.apply_progress(self.progress_value)
        self.progress_bar.setValue(self.progress_value)
        self._refresh_queue()
        self._set_status(f"Running '{self.active_operation}' operation... {self.progress_value}%")

    def _cancel_operation(self) -> None:
        if not self.timer.isActive():
            self._log("Cancel requested, but no operation was active.")
            self._set_status("No active operation to cancel.")
            return

        self.timer.stop()
        self.controller.fail_operation()
        failed_name = self.active_operation or "operation"
        self.active_operation = None
        self._refresh_queue()
        self._set_status(f"Cancelled '{failed_name}'.")
        self._log(f"Cancelled mock '{failed_name}' operation.")
        self.progress_bar.setValue(0)
        self._record_recent_job("Cancelled", failed_name)
        self.active_context = None
        self.active_source_label = ""
        self.active_target_label = ""

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