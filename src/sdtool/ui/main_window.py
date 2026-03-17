from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
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
    QPushButton,
    QComboBox,
    QTextEdit,
    QVBoxLayout,
    QWidget,
    QProgressBar,
)

from sdtool.models import mock_source_devices, mock_target_devices
from sdtool.workflow import StepStatus, WorkflowController

OPERATION_STEPS: dict[str, list[tuple[str, str]]] = {
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


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("SD Image Tool - Mock Mode")
        self.resize(1100, 760)

        self.controller = WorkflowController()
        self.active_operation: str | None = None
        self.progress_value = 0

        self.timer = QTimer(self)
        self.timer.setInterval(120)
        self.timer.timeout.connect(self._advance_mock_operation)

        self.source_devices = mock_source_devices()
        self.target_devices = mock_target_devices()

        self._build_ui()
        self._load_devices()
        self._log("Mock mode is enabled. No real disks are touched in this build.")
        self._set_status("Ready. Safe mock mode active.")

    def _build_ui(self) -> None:
        central = QWidget(self)
        self.setCentralWidget(central)

        root = QVBoxLayout(central)
        root.setSpacing(12)

        top_notice = QLabel(
            "This first build is intentionally non-destructive. "
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
        self.source_devices = mock_source_devices()
        self.target_devices = mock_target_devices()

        self.source_combo.clear()
        for device in self.source_devices:
            self.source_combo.addItem(device.label(), device.device_id)

        self.target_combo.clear()
        for device in self.target_devices:
            self.target_combo.addItem(device.label(), device.device_id)

        self._log("Refreshed mock device list.")
        self._set_status("Device list refreshed.")

    def _start_mock_operation(self, operation_name: str) -> None:
        if self.timer.isActive():
            QMessageBox.information(
                self,
                "Operation already running",
                "A task is already in progress. Cancel it first if you want to switch tasks.",
            )
            return

        step_definitions = OPERATION_STEPS[operation_name]
        self.controller.start_operation(operation_name, step_definitions)
        self.active_operation = operation_name
        self.progress_value = 1
        self.progress_bar.setValue(0)
        self._refresh_queue()

        image_path = self.image_path_edit.text().strip()
        self._log(
            f"Started mock '{operation_name}' operation. "
            f"Source={self.source_combo.currentData()} "
            f"Target={self.target_combo.currentData()} "
            f"Image={image_path}"
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
            self._set_status(f"Completed '{completed_name}' in mock mode.")
            self._log(f"Completed mock '{completed_name}' operation.")
            self.active_operation = None
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