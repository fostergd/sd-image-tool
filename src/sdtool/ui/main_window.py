from __future__ import annotations

from datetime import datetime
from pathlib import Path
import subprocess
from queue import Empty, Queue
from shutil import copystat, disk_usage
import threading
import time

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QProgressDialog,
    QPushButton,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from sdtool.backend import BackendInterface, MockBackend, OperationContext
from sdtool.formatting import describe_reduction, format_bytes
from sdtool.image_vault import (
    VaultImage,
    default_vault_path,
    next_available_image_path,
    record_import_metadata,
    scan_vault,
)
from sdtool.windows_raw import (
    CopyCancelledError,
    compare_image_to_physical_drive,
    copy_image_to_physical_drive,
    copy_physical_drive_to_image,
    get_physical_drive_size_bytes,
)
from sdtool.workflow import StepStatus, WorkflowController
from sdtool.wsl_setup import (
    build_manual_shrink_setup_help,
    build_shrink_setup_confirmation_text,
    get_shrink_setup_button_label,
    launch_shrink_setup,
)
from sdtool.wsl_shrink import (
    WslAvailabilityReport,
    WslCommandPlan,
    build_pishrink_plan,
    get_shrink_availability_report,
    start_pishrink_process,
)

MOCK_SAVE_MARKER = "SD IMAGE TOOL MOCK SAVE PLACEHOLDER"


class MainWindow(QMainWindow):
    def __init__(self, backend: BackendInterface | None = None) -> None:
        super().__init__()
        self.setWindowTitle("SD Image Tool")
        self.resize(930, 575)

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
        self.active_shrink_source_size: int | None = None
        self.shrink_progress_value = 0
        self.shrink_final_stage_logged = False
        self.delete_source_after_successful_shrink: Path | None = None

        self.shrink_output_queue: Queue[str] | None = None
        self.shrink_output_thread: threading.Thread | None = None
        self.shrink_last_output_monotonic = 0.0
        self.shrink_last_stall_notice_monotonic = 0.0

        self.copy_cancel_requested = False
        self.active_copy_mode: str | None = None
        self.active_copy_output_path: Path | None = None
        self.active_copy_target_device_id: str | None = None

        self.vault_path = default_vault_path()
        self.vault_images: list[VaultImage] = []

        self.current_disk_mode = "generic"
        self.has_available_disks = False
        self.shrink_ready = False
        self.shrink_availability_report: WslAvailabilityReport | None = None

        self._build_ui()
        self._load_devices()
        self._refresh_vault()
        self._refresh_shrink_readiness(log_result=False)
        self._set_disk_selector_mode("generic")
        self._refresh_action_button_states()
        self._log("Real save, write, and verify are enabled. Shrink can run in real WSL mode.")
        self._log(f"Image vault folder: {self.vault_path}")
        self._set_status("Ready. Real save/write/verify enabled.")

    def _build_ui(self) -> None:
        central = QWidget(self)
        self.setCentralWidget(central)

        root = QVBoxLayout(central)
        root.setSpacing(6)
        root.setContentsMargins(6, 6, 6, 6)

        top_notice = QLabel(
            "Save reads the selected SD card into an image file. "
            "Write writes the selected image to the selected SD card. "
            "Verify compares the selected image against the selected SD card. "
            "Shrink can run through WSL PiShrink."
        )
        top_notice.setWordWrap(True)
        root.addWidget(top_notice)

        self.main_tabs = QTabWidget()
        self.main_tabs.setDocumentMode(True)
        self.main_tabs.addTab(self._build_operations_tab(), "Operations")
        self.main_tabs.addTab(self._build_details_tab(), "Details / History")
        root.addWidget(self.main_tabs, 1)

        root.addWidget(self._build_footer_bar(), 0)

    def _build_operations_tab(self) -> QWidget:
        tab = QWidget()
        layout = QHBoxLayout(tab)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        layout.addWidget(self._build_vault_group(), 7)

        right_column = QVBoxLayout()
        right_column.setSpacing(6)
        right_column.addWidget(self._build_sources_group(), 0)
        right_column.addWidget(self._build_actions_group(), 0)
        right_column.addStretch(1)

        layout.addLayout(right_column, 4)
        return tab

    def _build_details_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        top_row = QHBoxLayout()
        top_row.setSpacing(6)
        top_row.addWidget(self._build_shrink_readiness_group(), 2)
        top_row.addWidget(self._build_last_result_group(), 3)
        layout.addLayout(top_row)

        bottom_row = QHBoxLayout()
        bottom_row.setSpacing(6)
        bottom_row.addWidget(self._build_queue_group(), 2)
        bottom_row.addWidget(self._build_recent_jobs_group(), 2)
        bottom_row.addWidget(self._build_log_group(), 4)
        layout.addLayout(bottom_row, 1)

        return tab

    def _build_sources_group(self) -> QGroupBox:
        group = QGroupBox("Device / File")
        group.setMinimumWidth(285)

        layout = QGridLayout(group)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setHorizontalSpacing(8)
        layout.setVerticalSpacing(4)

        self.disk_role_label = QLabel("SD/Card Reader")
        layout.addWidget(self.disk_role_label, 0, 0)

        self.disk_combo = QComboBox()
        self.disk_combo.currentIndexChanged.connect(self._refresh_action_button_states)
        layout.addWidget(self.disk_combo, 0, 1)

        self.refresh_devices_btn = QPushButton("Refresh Device List")
        self.refresh_devices_btn.clicked.connect(self._load_devices)
        layout.addWidget(self.refresh_devices_btn, 1, 1)

        layout.setRowMinimumHeight(2, 10)

        separator = QFrame()
        separator.setFrameShape(QFrame.HLine)
        separator.setFrameShadow(QFrame.Sunken)
        layout.addWidget(separator, 3, 0, 1, 2)

        layout.setRowMinimumHeight(4, 10)

        layout.addWidget(QLabel("Selected Image"), 5, 0)
        self.selected_image_value = QLabel("(none)")
        self.selected_image_value.setWordWrap(True)
        layout.addWidget(self.selected_image_value, 5, 1)

        layout.setColumnStretch(1, 1)
        return group

    def _build_vault_group(self) -> QGroupBox:
        group = QGroupBox("Vault Images")
        group.setMinimumWidth(360)

        layout = QVBoxLayout(group)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(6)

        path_label = QLabel(f"Stored with the app in:\n{self.vault_path}")
        path_label.setWordWrap(True)
        layout.addWidget(path_label)

        toolbar = QHBoxLayout()
        toolbar.setSpacing(6)

        self.import_btn = QPushButton("Import Image")
        self.import_btn.clicked.connect(self._import_image_into_vault)
        toolbar.addWidget(self.import_btn)

        self.delete_vault_btn = QPushButton("Delete Selected")
        self.delete_vault_btn.clicked.connect(self._delete_selected_vault_image)
        self.delete_vault_btn.setEnabled(False)
        toolbar.addWidget(self.delete_vault_btn)

        self.refresh_vault_btn = QPushButton("Refresh Vault")
        self.refresh_vault_btn.clicked.connect(self._refresh_vault)
        toolbar.addWidget(self.refresh_vault_btn)

        toolbar.addStretch(1)
        layout.addLayout(toolbar)

        self.vault_list = QListWidget()
        self.vault_list.itemSelectionChanged.connect(self._on_vault_selection_changed)
        self.vault_list.setMinimumWidth(320)
        self.vault_list.setMinimumHeight(395)
        self.vault_list.setWordWrap(True)
        self.vault_list.setSpacing(2)
        layout.addWidget(self.vault_list, 1)

        self.vault_summary_label = QLabel("No images found in the app vault.")
        self.vault_summary_label.setWordWrap(True)
        layout.addWidget(self.vault_summary_label, 0)

        return group

    def _build_actions_group(self) -> QGroupBox:
        group = QGroupBox("Actions")
        group.setMinimumWidth(285)

        layout = QVBoxLayout(group)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(22)

        self.write_btn = QPushButton("Write Selected Image to SD Card")
        self.write_btn.setMinimumHeight(48)
        self.write_btn.clicked.connect(self._start_write_operation)
        layout.addWidget(self.write_btn)

        self.save_btn = QPushButton("Save SD Card to Image File")
        self.save_btn.setMinimumHeight(48)
        self.save_btn.clicked.connect(self._start_save_operation)
        layout.addWidget(self.save_btn)

        self.shrink_btn = QPushButton("Shrink Selected Image File")
        self.shrink_btn.setMinimumHeight(48)
        self.shrink_btn.clicked.connect(self._start_shrink_operation)
        layout.addWidget(self.shrink_btn)

        self.verify_btn = QPushButton("Verify Selected Image Against SD Card")
        self.verify_btn.setMinimumHeight(48)
        self.verify_btn.clicked.connect(self._start_verify_operation)
        layout.addWidget(self.verify_btn)

        self.cancel_btn = QPushButton("Cancel Current Task")
        self.cancel_btn.setMinimumHeight(48)
        self.cancel_btn.clicked.connect(self._cancel_operation)
        layout.addWidget(self.cancel_btn)

        return group

    def _build_shrink_readiness_group(self) -> QGroupBox:
        group = QGroupBox("Shrink Readiness")
        group.setMinimumHeight(128)

        layout = QGridLayout(group)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setHorizontalSpacing(8)
        layout.setVerticalSpacing(4)

        layout.addWidget(QLabel("WSL + PiShrink"), 0, 0)
        self.shrink_readiness_value = QLabel("Checking...")
        self.shrink_readiness_value.setWordWrap(True)
        layout.addWidget(self.shrink_readiness_value, 0, 1)

        layout.addWidget(QLabel("Details"), 1, 0)
        self.shrink_readiness_detail_value = QLabel("-")
        self.shrink_readiness_detail_value.setWordWrap(True)
        layout.addWidget(self.shrink_readiness_detail_value, 1, 1)

        self.refresh_shrink_readiness_btn = QPushButton("Re-check Shrink Readiness")
        self.refresh_shrink_readiness_btn.clicked.connect(self._refresh_shrink_readiness)
        layout.addWidget(self.refresh_shrink_readiness_btn, 2, 0)

        self.install_shrink_setup_btn = QPushButton("Install / Repair Shrink Support")
        self.install_shrink_setup_btn.clicked.connect(self._install_or_repair_shrink_support)
        layout.addWidget(self.install_shrink_setup_btn, 2, 1)

        self.show_shrink_help_btn = QPushButton("Show Setup Help")
        self.show_shrink_help_btn.clicked.connect(self._show_shrink_setup_help)
        layout.addWidget(self.show_shrink_help_btn, 3, 0, 1, 2)

        layout.setColumnStretch(1, 1)
        return group

    def _build_last_result_group(self) -> QGroupBox:
        group = QGroupBox("Last Shrink Result")
        group.setMinimumHeight(150)

        layout = QGridLayout(group)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setHorizontalSpacing(8)
        layout.setVerticalSpacing(4)

        layout.addWidget(QLabel("Status"), 0, 0)
        self.result_status_value = QLabel("No shrink completed yet.")
        self.result_status_value.setWordWrap(True)
        layout.addWidget(self.result_status_value, 0, 1)

        layout.addWidget(QLabel("Original Size"), 1, 0)
        self.result_input_size_value = QLabel("-")
        layout.addWidget(self.result_input_size_value, 1, 1)

        layout.addWidget(QLabel("Shrunk Size"), 2, 0)
        self.result_output_size_value = QLabel("-")
        layout.addWidget(self.result_output_size_value, 2, 1)

        layout.addWidget(QLabel("Space Saved"), 3, 0)
        self.result_saved_value = QLabel("-")
        layout.addWidget(self.result_saved_value, 3, 1)

        layout.addWidget(QLabel("Output Path"), 4, 0)
        self.result_output_path_value = QLabel("-")
        self.result_output_path_value.setWordWrap(True)
        layout.addWidget(self.result_output_path_value, 4, 1)

        layout.setColumnStretch(1, 1)
        return group

    def _build_queue_group(self) -> QGroupBox:
        group = QGroupBox("Planned / Running Steps")
        group.setMinimumHeight(245)

        layout = QVBoxLayout(group)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(4)
        self.queue_list = QListWidget()
        layout.addWidget(self.queue_list)
        return group

    def _build_recent_jobs_group(self) -> QGroupBox:
        group = QGroupBox("Recent Jobs")
        group.setMinimumHeight(245)

        layout = QVBoxLayout(group)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(4)

        help_label = QLabel(
            "Completed, failed, and cancelled operations appear here with the device selections and image path used."
        )
        help_label.setWordWrap(True)
        layout.addWidget(help_label)

        self.recent_jobs_list = QListWidget()
        layout.addWidget(self.recent_jobs_list)

        return group

    def _build_log_group(self) -> QGroupBox:
        group = QGroupBox("Activity Log")
        group.setMinimumHeight(245)

        layout = QVBoxLayout(group)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(4)
        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        layout.addWidget(self.log_view)
        return group

    def _build_footer_bar(self) -> QWidget:
        footer = QGroupBox("Status")
        footer.setMaximumHeight(126)

        layout = QGridLayout(footer)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setHorizontalSpacing(12)
        layout.setVerticalSpacing(4)

        layout.addWidget(QLabel("Current Status"), 0, 0)
        self.status_label = QLabel("Ready.")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label, 0, 1, 1, 5)

        layout.addWidget(QLabel("Progress"), 1, 0)
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        layout.addWidget(self.progress_bar, 1, 1, 2, 2)

        drive_size_title = QLabel("Drive Size")
        drive_size_title.setAlignment(Qt.AlignHCenter | Qt.AlignBottom)
        layout.addWidget(drive_size_title, 1, 3)
        self.drive_size_value = QLabel("-")
        self.drive_size_value.setAlignment(Qt.AlignHCenter | Qt.AlignTop)
        self.drive_size_value.setWordWrap(True)
        layout.addWidget(self.drive_size_value, 2, 3)

        drive_free_title = QLabel("Drive Free Space")
        drive_free_title.setAlignment(Qt.AlignHCenter | Qt.AlignBottom)
        layout.addWidget(drive_free_title, 1, 4)
        self.drive_free_value = QLabel("-")
        self.drive_free_value.setAlignment(Qt.AlignHCenter | Qt.AlignTop)
        self.drive_free_value.setWordWrap(True)
        layout.addWidget(self.drive_free_value, 2, 4)

        vault_size_title = QLabel("Vault Size")
        vault_size_title.setAlignment(Qt.AlignHCenter | Qt.AlignBottom)
        layout.addWidget(vault_size_title, 1, 5)
        self.vault_size_value = QLabel("-")
        self.vault_size_value.setAlignment(Qt.AlignHCenter | Qt.AlignTop)
        self.vault_size_value.setWordWrap(True)
        layout.addWidget(self.vault_size_value, 2, 5)

        layout.setColumnStretch(1, 3)
        layout.setColumnStretch(2, 2)
        layout.setColumnStretch(3, 1)
        layout.setColumnStretch(4, 1)
        layout.setColumnStretch(5, 1)

        return footer

    def closeEvent(self, event) -> None:
        if self.active_copy_mode in {"save", "write", "verify"}:
            reply = QMessageBox.question(
                self,
                "Operation in progress",
                f"A {self.active_copy_mode} is still running.\n\nCancel it first?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if reply != QMessageBox.Yes:
                event.ignore()
                return

            self.copy_cancel_requested = True
            self._set_status(f"Cancelling '{self.active_copy_mode}' before close...")
            self._log(f"Close requested during real {self.active_copy_mode}. Cancellation requested.")
            event.ignore()
            return

        if not self._operation_is_running():
            event.accept()
            return

        reply = QMessageBox.question(
            self,
            "Operation in progress",
            "A task is still running.\n\nCancel it and close the app?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            event.ignore()
            return

        self._cancel_operation_for_close()
        event.accept()

    def _start_shrink_output_reader(self) -> None:
        process = self.active_shrink_process
        if process is None or process.stdout is None:
            self.shrink_output_queue = None
            self.shrink_output_thread = None
            return

        self.shrink_output_queue = Queue()

        def reader() -> None:
            assert process.stdout is not None
            try:
                for raw_line in process.stdout:
                    line = raw_line.rstrip()
                    if line:
                        self.shrink_output_queue.put(line)
            finally:
                try:
                    process.stdout.close()
                except Exception:
                    pass

        self.shrink_output_thread = threading.Thread(target=reader, daemon=True)
        self.shrink_output_thread.start()
        self.shrink_last_output_monotonic = time.monotonic()
        self.shrink_last_stall_notice_monotonic = 0.0

    def _drain_shrink_output_queue(self) -> None:
        if self.shrink_output_queue is None:
            return

        while True:
            try:
                line = self.shrink_output_queue.get_nowait()
            except Empty:
                break

            self.shrink_last_output_monotonic = time.monotonic()
            self._log(f"PiShrink: {line}")

    def _finalize_shrink_output_reader(self) -> None:
        self._drain_shrink_output_queue()
        if self.shrink_output_thread is not None:
            self.shrink_output_thread.join(timeout=0.5)
        self._drain_shrink_output_queue()

    def _terminate_process(self, process: subprocess.Popen[str]) -> None:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)

    def _set_last_result(
        self,
        *,
        status: str = "-",
        original_size: str = "-",
        output_size: str = "-",
        saved: str = "-",
        output_path: str = "-",
    ) -> None:
        self.result_status_value.setText(status)
        self.result_input_size_value.setText(original_size)
        self.result_output_size_value.setText(output_size)
        self.result_saved_value.setText(saved)
        self.result_output_path_value.setText(output_path)

    def _refresh_shrink_readiness(self, *, log_result: bool = True) -> None:
        self.shrink_availability_report = get_shrink_availability_report()
        self.shrink_ready = self.shrink_availability_report.is_ready
        self.shrink_readiness_value.setText(self.shrink_availability_report.summary)
        self.shrink_readiness_detail_value.setText(self.shrink_availability_report.detail)
        self.install_shrink_setup_btn.setText(get_shrink_setup_button_label(self.shrink_availability_report))

        if log_result:
            self._log(
                f"Shrink readiness checked: {self.shrink_availability_report.code} - "
                f"{self.shrink_availability_report.summary}"
            )

        self._refresh_action_button_states()

    def _install_or_repair_shrink_support(self) -> None:
        report = self.shrink_availability_report or get_shrink_availability_report()
        self.shrink_availability_report = report
        self.shrink_ready = report.is_ready
        self.shrink_readiness_value.setText(report.summary)
        self.shrink_readiness_detail_value.setText(report.detail)
        self.install_shrink_setup_btn.setText(get_shrink_setup_button_label(report))

        reply = QMessageBox.question(
            self,
            "Install or repair shrink support",
            build_shrink_setup_confirmation_text(report),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            self._log("Shrink setup launch cancelled at confirmation dialog.")
            return

        launched, detail = launch_shrink_setup(report=report)
        if not launched:
            QMessageBox.critical(
                self,
                "Could not start shrink setup",
                f"The app could not start the shrink setup helper.\n\n{detail}",
            )
            self._log(f"Shrink setup helper launch failed: {detail}")
            return

        self._set_status(f"{report.summary} helper started.")
        self._log(f"Started shrink setup helper: {detail}")

    def _show_shrink_setup_help(self) -> None:
        report = self.shrink_availability_report or get_shrink_availability_report()
        self.shrink_availability_report = report
        self.shrink_ready = report.is_ready
        self.shrink_readiness_value.setText(report.summary)
        self.shrink_readiness_detail_value.setText(report.detail)

        help_text = build_manual_shrink_setup_help(report=report)
        QMessageBox.information(
            self,
            "Shrink setup help",
            help_text,
        )

    def _normalized_device_label(self, label: str) -> str:
        return label.replace(" - Source", "").replace(" - Target", "")

    def _set_disk_selector_mode(self, mode: str) -> None:
        self.current_disk_mode = mode

        if mode == "save":
            self.disk_role_label.setText("Source SD/Card Reader")
            return

        if mode in {"write", "verify"}:
            self.disk_role_label.setText("Target SD/Card Reader")
            return

        self.disk_role_label.setText("SD/Card Reader")

    def _selected_disk_label(self) -> str:
        if self.disk_combo.currentData() is None:
            return "(none)"
        return self.disk_combo.currentText()

    def _selected_vault_image_path(self) -> Path | None:
        item = self.vault_list.currentItem()
        if item is None:
            return None

        image_path = item.data(256)
        if not image_path:
            return None

        return Path(image_path)

    def _is_mock_placeholder_image(self, image_path: Path) -> bool:
        try:
            with image_path.open("r", encoding="utf-8", errors="ignore") as handle:
                first_line = handle.readline().strip()
            return first_line == MOCK_SAVE_MARKER
        except OSError:
            return False

    def _operation_is_running(self) -> bool:
        return (
            self.active_operation is not None
            or self.timer.isActive()
            or self.shrink_poll_timer.isActive()
        )

    def _show_mock_placeholder_blocked_message(self, operation_name: str, image_path: Path) -> None:
        action_name = {
            "write": "written to an SD card",
            "verify": "used for verify",
            "shrink": "shrunk",
        }.get(operation_name, "used")

        QMessageBox.warning(
            self,
            "Cannot use mock placeholder",
            f"The selected file was created by the mock Save flow and is not a real disk image.\n\n"
            f"It cannot be {action_name}.",
        )
        self._log(f"{operation_name.capitalize()} blocked because selected image is a mock placeholder: {image_path}")

    def _update_selected_image_display(self) -> None:
        selected_path = self._selected_vault_image_path()
        if selected_path is None:
            self.selected_image_value.setText("(none)")
        elif self._is_mock_placeholder_image(selected_path):
            self.selected_image_value.setText(f"{selected_path} [Mock Placeholder]")
        else:
            self.selected_image_value.setText(str(selected_path))

    def _refresh_action_button_states(self) -> None:
        operation_running = self._operation_is_running() or self.active_copy_mode is not None
        selected_image_path = self._selected_vault_image_path()
        selected_disk_present = self.disk_combo.currentData() is not None
        has_real_image = selected_image_path is not None and not self._is_mock_placeholder_image(selected_image_path)
        has_any_selected_image = selected_image_path is not None

        self.save_btn.setEnabled(not operation_running and selected_disk_present)
        self.write_btn.setEnabled(not operation_running and selected_disk_present and has_real_image)
        self.verify_btn.setEnabled(not operation_running and selected_disk_present and has_real_image)
        self.shrink_btn.setEnabled(not operation_running and has_real_image)
        self.cancel_btn.setEnabled(operation_running)
        self.delete_vault_btn.setEnabled(not operation_running and has_any_selected_image)
        self.import_btn.setEnabled(not operation_running)
        self.refresh_devices_btn.setEnabled(not operation_running)
        self.refresh_vault_btn.setEnabled(not operation_running)
        self.refresh_shrink_readiness_btn.setEnabled(not operation_running)
        self.vault_list.setEnabled(not operation_running)
        self.disk_combo.setEnabled(self.has_available_disks and not operation_running)
        self.main_tabs.setEnabled(True)

    def _load_devices(self) -> None:
        current_disk_id = self.disk_combo.currentData() if hasattr(self, "disk_combo") else None

        source_devices = self.backend.list_source_devices()
        target_devices = self.backend.list_target_devices()

        unified_devices: list[tuple[str, str | None]] = []
        seen_labels: set[str] = set()

        for device in [*source_devices, *target_devices]:
            label = self._normalized_device_label(device.label())
            if label in seen_labels:
                continue
            seen_labels.add(label)
            unified_devices.append((label, device.device_id))

        self.disk_combo.clear()

        if not unified_devices:
            self.has_available_disks = False
            self.disk_combo.addItem("No removable disks found", None)
            self._set_status("No removable disks detected. Insert a card reader or click Refresh Device List.")
        else:
            self.has_available_disks = True
            for label, device_id in unified_devices:
                self.disk_combo.addItem(label, device_id)

            if current_disk_id is not None:
                for index in range(self.disk_combo.count()):
                    if self.disk_combo.itemData(index) == current_disk_id:
                        self.disk_combo.setCurrentIndex(index)
                        break

            self._set_status("Device list refreshed.")

        self._set_disk_selector_mode(self.current_disk_mode)
        self._refresh_action_button_states()
        self._log("Refreshed device list from backend.")

    def _refresh_drive_status(self) -> None:
        try:
            usage_target = self.vault_path if self.vault_path.exists() else self.vault_path.parent
            usage = disk_usage(usage_target)
            vault_size = sum(image.size_bytes for image in self.vault_images)

            self.drive_size_value.setText(format_bytes(usage.total))
            self.drive_free_value.setText(format_bytes(usage.free))
            self.vault_size_value.setText(format_bytes(vault_size))
        except OSError as exc:
            self.drive_size_value.setText("Unavailable")
            self.drive_free_value.setText("Unavailable")
            self.vault_size_value.setText("Unavailable")
            self._log(f"Could not read tool drive status: {exc}")

    def _refresh_vault(self, *, select_path: Path | None = None) -> None:
        current_selected_path = select_path or self._selected_vault_image_path()

        self.vault_images = scan_vault(self.vault_path)
        self.vault_list.clear()
        self.delete_vault_btn.setEnabled(False)

        for image in self.vault_images:
            image_is_mock = self._is_mock_placeholder_image(image.path)

            line1 = image.filename
            if image_is_mock:
                line1 = f"{line1} [Mock]"

            line2 = f"{image.formatted_size} | {image.formatted_modified} | {image.status_text}"
            if image_is_mock:
                line2 = f"{line2} | Mock placeholder"

            text = f"{line1}\n{line2}"

            item = QListWidgetItem(text)
            item.setData(256, str(image.path))
            item.setSizeHint(QSize(item.sizeHint().width(), item.sizeHint().height() + 6))

            tooltip_lines = [
                f"Path: {image.path}",
                f"Size: {image.formatted_size}",
                f"Modified: {image.formatted_modified}",
                f"Status: {image.status_text}",
            ]
            if image_is_mock:
                tooltip_lines.append("Mock placeholder: Yes")
            if image.original_filename:
                tooltip_lines.append(f"Original filename: {image.original_filename}")
            if image.imported_at:
                tooltip_lines.append(f"Imported: {image.imported_at}")
            item.setToolTip("\n".join(tooltip_lines))
            self.vault_list.addItem(item)

        count = len(self.vault_images)
        if count == 0:
            self.vault_summary_label.setText("No images found in the app vault.")
        elif count == 1:
            self.vault_summary_label.setText("1 image found in the app vault.")
        else:
            self.vault_summary_label.setText(f"{count} images found in the app vault.")

        if current_selected_path is not None:
            select_text = str(current_selected_path)
            for index in range(self.vault_list.count()):
                item = self.vault_list.item(index)
                if item.data(256) == select_text:
                    self.vault_list.setCurrentItem(item)
                    break

        self._update_selected_image_display()
        self._refresh_drive_status()
        self._refresh_action_button_states()
        self._log(f"Vault refreshed. Found {count} image(s).")

    def _on_vault_selection_changed(self) -> None:
        selected_path = self._selected_vault_image_path()
        self._update_selected_image_display()
        self._refresh_action_button_states()

        if selected_path is None:
            return

        if self._is_mock_placeholder_image(selected_path):
            self._log(f"Selected mock placeholder image: {selected_path}")
        else:
            self._log(f"Selected vault image: {selected_path}")

    def _delete_selected_vault_image(self) -> None:
        selected_path = self._selected_vault_image_path()
        if selected_path is None:
            QMessageBox.information(
                self,
                "No image selected",
                "Select an image in the vault list before trying to delete it.",
            )
            return

        reply = QMessageBox.question(
            self,
            "Delete image",
            f"Delete this image from the vault?\n\n{selected_path.name}",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        try:
            selected_path.unlink()
            self._refresh_vault()
            self._set_status("Vault image deleted.")
            self._log(f"Deleted vault image: {selected_path}")
        except OSError as exc:
            QMessageBox.critical(
                self,
                "Delete failed",
                f"Could not delete the selected image:\n{exc}",
            )
            self._log(f"Delete failed for vault image {selected_path}: {exc}")

    def _copy_file_with_progress(self, source_path: Path, target_path: Path) -> None:
        total_size = source_path.stat().st_size
        bytes_copied = 0
        chunk_size = 8 * 1024 * 1024

        progress = QProgressDialog("Importing image into vault...", None, 0, 100, self)
        progress.setWindowTitle("Importing Image")
        progress.setWindowModality(Qt.WindowModal)
        progress.setMinimumDuration(0)
        progress.setAutoClose(True)
        progress.setValue(0)
        progress.show()
        QApplication.processEvents()

        try:
            with source_path.open("rb") as src, target_path.open("wb") as dst:
                while True:
                    chunk = src.read(chunk_size)
                    if not chunk:
                        break

                    dst.write(chunk)
                    bytes_copied += len(chunk)

                    if total_size > 0:
                        percent = min(100, int((bytes_copied / total_size) * 100))
                    else:
                        percent = 100

                    progress.setValue(percent)
                    progress.setLabelText(
                        f"Importing image into vault...\n{source_path.name}\n{format_bytes(bytes_copied)} of {format_bytes(total_size)}"
                    )
                    QApplication.processEvents()

            copystat(source_path, target_path)
            progress.setValue(100)
            QApplication.processEvents()
        except Exception:
            if target_path.exists():
                try:
                    target_path.unlink()
                except OSError:
                    pass
            raise
        finally:
            progress.close()

    def _remove_incomplete_shrink_output(self, *, log_prefix: str) -> None:
        if self.active_shrink_plan is None:
            return

        output_path = Path(self.active_shrink_plan.output_path_windows)
        if not output_path.exists():
            return

        try:
            output_path.unlink()
            self._log(f"{log_prefix}: removed incomplete shrink output: {output_path}")
        except OSError as exc:
            self._log(f"{log_prefix}: could not remove incomplete shrink output {output_path}: {exc}")

    def _import_image_into_vault(self) -> None:
        filename, _ = QFileDialog.getOpenFileName(
            self,
            "Import image into vault",
            str(self.vault_path),
            "Image Files (*.img);;All Files (*.*)",
        )
        if not filename:
            return

        source_path = Path(filename)
        if not source_path.exists() or not source_path.is_file():
            QMessageBox.warning(
                self,
                "Image file not found",
                "The selected image file does not exist or is not a normal file.",
            )
            return

        shrunk_reply = QMessageBox.question(
            self,
            "Already shrunk?",
            "Is this image already shrunk?",
            QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel,
            QMessageBox.No,
        )
        if shrunk_reply == QMessageBox.Cancel:
            return

        is_shrunk = shrunk_reply == QMessageBox.Yes
        shrink_after_import = False

        if not is_shrunk:
            shrink_reply = QMessageBox.question(
                self,
                "Shrink after import?",
                "Import this image and immediately start shrinking the vault copy?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            shrink_after_import = shrink_reply == QMessageBox.Yes

        try:
            if source_path.parent.resolve() == self.vault_path.resolve():
                target_path = source_path
            else:
                target_path = next_available_image_path(self.vault_path, source_path.name)
                self._set_status("Importing image into vault...")
                self._copy_file_with_progress(source_path, target_path)

            record_import_metadata(
                self.vault_path,
                target_path.name,
                is_shrunk=is_shrunk,
                original_filename=source_path.name,
            )

            self._refresh_vault(select_path=target_path)
            self._log(f"Imported image into vault: {target_path}")
            self._set_status("Import completed.")

            if shrink_after_import:
                self.delete_source_after_successful_shrink = target_path
                self._set_disk_selector_mode("shrink")
                self._start_operation("shrink")
        except OSError as exc:
            QMessageBox.critical(self, "Import failed", f"Could not import image: {exc}")
            self._log(f"Import failed: {exc}")
            self._set_status("Import failed.")

    def _start_save_operation(self) -> None:
        self._set_disk_selector_mode("save")

        if self.disk_combo.currentData() is None:
            QMessageBox.warning(
                self,
                "Cannot start operation",
                "A source SD/card reader is required for this operation.",
            )
            self._log("Operation 'save' was blocked because no device was selected.")
            return

        image_name_base, ok = QInputDialog.getText(
            self,
            "New image name",
            "Enter a name for the new image file.\n.img will be added automatically.",
            text="new-image",
        )
        if not ok:
            return

        image_name_base = image_name_base.strip()
        if image_name_base.lower().endswith(".img"):
            image_name_base = image_name_base[:-4].strip()

        if not image_name_base:
            QMessageBox.warning(
                self,
                "Invalid image name",
                "Enter a file name for the new image.",
            )
            return

        image_name = f"{image_name_base}.img"
        save_path = next_available_image_path(self.vault_path, image_name)

        reply = QMessageBox.question(
            self,
            "Confirm save",
            "Read the selected SD card into a new image file?\n\n"
            f"Source: {self._selected_disk_label()}\n"
            f"Output: {save_path.name}",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            self._log("Save operation cancelled at confirmation dialog.")
            return

        self._start_operation("save", image_path_override=str(save_path))

    def _start_write_operation(self) -> None:
        self._set_disk_selector_mode("write")

        selected_disk_id = self.disk_combo.currentData()
        selected_image_path = self._selected_vault_image_path()

        if selected_disk_id is None or selected_image_path is None:
            self._start_operation("write")
            return

        if self._is_mock_placeholder_image(selected_image_path):
            self._show_mock_placeholder_blocked_message("write", selected_image_path)
            return

        reply = QMessageBox.question(
            self,
            "Confirm write",
            "Write the selected image to the selected SD card?\n\n"
            "This will overwrite the target device.\n\n"
            f"Image: {selected_image_path.name}\n"
            f"Target: {self._selected_disk_label()}",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            self._log("Write operation cancelled at confirmation dialog.")
            return

        self._start_operation("write")

    def _start_shrink_operation(self) -> None:
        self._set_disk_selector_mode("shrink")
        self._start_operation("shrink")

    def _start_verify_operation(self) -> None:
        self._set_disk_selector_mode("verify")

        selected_disk_id = self.disk_combo.currentData()
        selected_image_path = self._selected_vault_image_path()

        if selected_disk_id is None or selected_image_path is None:
            self._start_operation("verify")
            return

        if self._is_mock_placeholder_image(selected_image_path):
            self._show_mock_placeholder_blocked_message("verify", selected_image_path)
            return

        reply = QMessageBox.question(
            self,
            "Confirm verify",
            "Compare the selected image against the selected SD card?\n\n"
            f"Image: {selected_image_path.name}\n"
            f"Target: {self._selected_disk_label()}",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            self._log("Verify operation cancelled at confirmation dialog.")
            return

        self._start_operation("verify")

    def _start_operation(self, operation_name: str, *, image_path_override: str | None = None) -> None:
        if self.timer.isActive() or self.shrink_poll_timer.isActive() or self.active_copy_mode is not None:
            QMessageBox.information(
                self,
                "Operation already running",
                "A task is already in progress. Cancel it first if you want to switch tasks.",
            )
            return

        selected_disk_id = self.disk_combo.currentData()
        selected_image_path = image_path_override

        if selected_image_path is None:
            selected_vault_path = self._selected_vault_image_path()
            selected_image_path = str(selected_vault_path) if selected_vault_path is not None else ""

        if operation_name in {"save", "write", "verify"} and selected_disk_id is None:
            role_text = "source SD/card reader" if operation_name == "save" else "target SD/card reader"
            QMessageBox.warning(
                self,
                "Cannot start operation",
                f"A {role_text} is required for this operation.",
            )
            self._log(f"Operation '{operation_name}' was blocked because no device was selected.")
            return

        if operation_name in {"write", "shrink", "verify"} and not selected_image_path.strip():
            QMessageBox.warning(
                self,
                "Cannot start operation",
                "Select an image in the vault before starting this operation.",
            )
            self._log(f"Operation '{operation_name}' was blocked because no image was selected.")
            return

        if operation_name in {"write", "verify", "shrink"}:
            selected_real_path = Path(selected_image_path)
            if self._is_mock_placeholder_image(selected_real_path):
                self._show_mock_placeholder_blocked_message(operation_name, selected_real_path)
                return

        context = OperationContext(
            operation_name=operation_name,
            source_device_id=selected_disk_id if operation_name == "save" else None,
            target_device_id=selected_disk_id if operation_name in {"write", "verify"} else None,
            image_path=selected_image_path.strip(),
        )

        warnings = self.backend.validate_operation(context)
        if warnings:
            QMessageBox.warning(self, "Cannot start operation", "\n".join(warnings))
            self._log(f"Operation '{context.operation_name}' was blocked by validation.")
            return

        if operation_name == "save":
            self._start_real_save_operation(context)
            return

        if operation_name == "write":
            self._start_real_write_operation(context)
            return

        if operation_name == "verify":
            self._start_real_verify_operation(context)
            return

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

        selected_label = self._selected_disk_label()
        if context.operation_name == "save":
            self.active_source_label = selected_label
            self.active_target_label = ""
        elif context.operation_name in {"write", "verify"}:
            self.active_source_label = ""
            self.active_target_label = selected_label
        else:
            self.active_source_label = ""
            self.active_target_label = ""

        self.progress_value = 1
        self.progress_bar.setValue(0)
        self._refresh_queue()
        self._refresh_action_button_states()

        self._log(
            f"Started mock '{context.operation_name}' operation. "
            f"Source={context.source_device_id} "
            f"Target={context.target_device_id} "
            f"Image={context.image_path}"
        )
        self._set_status(f"Running '{context.operation_name}' operation...")
        self.timer.start()

    def _on_real_save_progress(self, bytes_copied: int, total_size: int) -> None:
        percent = 0
        if total_size > 0:
            percent = min(98, int((bytes_copied / total_size) * 100))

        self.progress_bar.setValue(percent)
        self._set_status(
            f"Saving SD card to image... {percent}% "
            f"({format_bytes(bytes_copied)} of {format_bytes(total_size)})"
        )
        QApplication.processEvents()

    def _on_real_write_progress(self, bytes_written: int, total_size: int) -> None:
        percent = 0
        if total_size > 0:
            percent = min(98, int((bytes_written / total_size) * 100))

        self.progress_bar.setValue(percent)
        self._set_status(
            f"Writing image to SD card... {percent}% "
            f"({format_bytes(bytes_written)} of {format_bytes(total_size)})"
        )
        QApplication.processEvents()

    def _on_real_verify_progress(self, bytes_verified: int, total_size: int) -> None:
        percent = 0
        if total_size > 0:
            percent = min(98, int((bytes_verified / total_size) * 100))

        self.progress_bar.setValue(percent)
        self._set_status(
            f"Verifying image against SD card... {percent}% "
            f"({format_bytes(bytes_verified)} of {format_bytes(total_size)})"
        )
        QApplication.processEvents()

    def _start_real_save_operation(self, context: OperationContext) -> None:
        output_path = Path(context.image_path)
        auto_shrink_output_path: Path | None = None

        try:
            total_size = get_physical_drive_size_bytes(context.source_device_id or "")
            if total_size is None:
                raise RuntimeError(
                    "Could not determine the selected device size. "
                    "Run the app as Administrator and try again."
                )

            step_definitions = self.backend.get_operation_steps("save")
        except Exception as exc:
            QMessageBox.critical(self, "Cannot start save", str(exc))
            self._log(f"Save preparation failed: {exc}")
            return

        self.controller.start_operation("save", step_definitions)
        self.controller.set_running_step(1)
        self.active_operation = "save"
        self.active_context = context
        self.active_source_label = self._selected_disk_label()
        self.active_target_label = ""
        self.copy_cancel_requested = False
        self.active_copy_mode = "save"
        self.active_copy_output_path = output_path
        self.active_copy_target_device_id = None
        self.progress_bar.setValue(0)
        self._refresh_queue()
        self._refresh_action_button_states()

        self._log(f"Prepared real save from: {context.source_device_id}")
        self._log(f"Selected source device: {self.active_source_label}")
        self._log(f"Save output image: {output_path}")
        self._log(f"Expected image size: {format_bytes(total_size)}")
        self._set_status("Starting SD card read to image file...")

        try:
            self.controller.set_running_step(2)
            self._refresh_queue()

            bytes_copied = copy_physical_drive_to_image(
                context.source_device_id or "",
                output_path,
                progress_callback=self._on_real_save_progress,
                cancel_callback=lambda: self.copy_cancel_requested,
            )

            self.controller.set_running_step(3)
            self._refresh_queue()

            actual_size = output_path.stat().st_size
            if actual_size != total_size or bytes_copied != total_size:
                raise RuntimeError(
                    "Saved image size did not match the expected device size."
                )

            record_import_metadata(
                self.vault_path,
                output_path.name,
                is_shrunk=False,
                original_filename=self.active_source_label or output_path.name,
            )

            self.controller.complete_operation()
            self.progress_bar.setValue(100)
            self._refresh_queue()
            self._refresh_vault(select_path=output_path)

            self._set_status(f"Saved SD card to image successfully. {format_bytes(actual_size)}")
            self._log(f"Completed real save operation: {output_path}")
            self._record_recent_job("Completed", "save")

            readiness_report = get_shrink_availability_report()
            self.shrink_availability_report = readiness_report
            self.shrink_ready = readiness_report.is_ready
            self.shrink_readiness_value.setText(readiness_report.summary)
            self.shrink_readiness_detail_value.setText(readiness_report.detail)

            if readiness_report.is_ready:
                auto_shrink_output_path = output_path
                self._log(f"PiShrink is available. Auto-starting shrink for saved image: {output_path}")
            else:
                self._log(
                    f"Image saved. Automatic shrink is unavailable: {readiness_report.summary}. {readiness_report.detail}"
                )
                self._set_status("Image saved. Shrink is unavailable on this machine right now.")
        except CopyCancelledError:
            if output_path.exists():
                try:
                    output_path.unlink()
                    self._log(f"Removed partial saved image after cancellation: {output_path}")
                except OSError as exc:
                    self._log(f"Could not remove partial saved image after cancellation: {exc}")

            self.controller.fail_operation()
            self._refresh_queue()
            self.progress_bar.setValue(0)
            self._set_status("Cancelled 'save'.")
            self._log("Cancelled real save operation.")
            self._record_recent_job("Cancelled", "save")
            self._refresh_vault()
        except Exception as exc:
            if output_path.exists():
                try:
                    output_path.unlink()
                    self._log(f"Removed incomplete saved image after failure: {output_path}")
                except OSError as cleanup_exc:
                    self._log(f"Could not remove incomplete saved image after failure: {cleanup_exc}")

            self.controller.fail_operation()
            self._refresh_queue()
            self.progress_bar.setValue(0)
            self._set_status("Save failed.")
            self._log(f"Real save failed: {exc}")
            self._record_recent_job("Failed", "save")
            self._refresh_vault()
            QMessageBox.critical(
                self,
                "Save failed",
                f"Could not save the SD card to an image file:\n{exc}",
            )
        finally:
            self.copy_cancel_requested = False
            self._clear_active_operation_state()
            self._refresh_action_button_states()

        if auto_shrink_output_path is not None and auto_shrink_output_path.exists():
            self.delete_source_after_successful_shrink = auto_shrink_output_path
            self._refresh_vault(select_path=auto_shrink_output_path)
            self._set_disk_selector_mode("shrink")
            self._start_operation("shrink")

    def _start_real_write_operation(self, context: OperationContext) -> None:
        image_path = Path(context.image_path)
        target_device_id = context.target_device_id or ""

        try:
            image_size = image_path.stat().st_size
            if image_size <= 0:
                raise RuntimeError("The selected image file is empty.")

            target_size = get_physical_drive_size_bytes(target_device_id)
            if target_size is None:
                raise RuntimeError(
                    "Could not determine the size of the selected target device. "
                    "Run the app as Administrator and try again."
                )

            if image_size > target_size:
                raise RuntimeError("The selected image is larger than the target device.")

            step_definitions = self.backend.get_operation_steps("write")
        except Exception as exc:
            QMessageBox.critical(self, "Cannot start write", str(exc))
            self._log(f"Write preparation failed: {exc}")
            return

        self.controller.start_operation("write", step_definitions)
        self.controller.set_running_step(1)
        self.active_operation = "write"
        self.active_context = context
        self.active_source_label = ""
        self.active_target_label = self._selected_disk_label()
        self.copy_cancel_requested = False
        self.active_copy_mode = "write"
        self.active_copy_output_path = None
        self.active_copy_target_device_id = target_device_id
        self.progress_bar.setValue(0)
        self._refresh_queue()
        self._refresh_action_button_states()

        self._log(f"Prepared real write to: {target_device_id}")
        self._log(f"Selected target device: {self.active_target_label}")
        self._log(f"Write source image: {image_path}")
        self._log(f"Image size: {format_bytes(image_size)}")
        self._log(f"Target size: {format_bytes(target_size)}")
        self._set_status("Starting image write to SD card...")

        try:
            self.controller.set_running_step(2)
            self._refresh_queue()

            bytes_written = copy_image_to_physical_drive(
                image_path,
                target_device_id,
                progress_callback=self._on_real_write_progress,
                cancel_callback=lambda: self.copy_cancel_requested,
            )

            self.controller.set_running_step(3)
            self._refresh_queue()

            if bytes_written != image_size:
                raise RuntimeError("Write completed with an unexpected byte count.")

            self.controller.complete_operation()
            self.progress_bar.setValue(100)
            self._refresh_queue()
            self._set_status(f"Wrote image to SD card successfully. {format_bytes(bytes_written)}")
            self._log(f"Completed real write operation to: {target_device_id}")
            self._record_recent_job("Completed", "write")
        except CopyCancelledError:
            self.controller.fail_operation()
            self._refresh_queue()
            self.progress_bar.setValue(0)
            self._set_status("Cancelled 'write'. Target device may contain partial image data.")
            self._log("Cancelled real write operation. Target device may contain partial image data.")
            self._record_recent_job("Cancelled", "write")
        except Exception as exc:
            self.controller.fail_operation()
            self._refresh_queue()
            self.progress_bar.setValue(0)
            self._set_status("Write failed.")
            self._log(f"Real write failed: {exc}")
            self._record_recent_job("Failed", "write")
            QMessageBox.critical(
                self,
                "Write failed",
                f"Could not write the image to the selected SD card:\n{exc}",
            )
        finally:
            self.copy_cancel_requested = False
            self._clear_active_operation_state()
            self._refresh_action_button_states()

    def _start_real_verify_operation(self, context: OperationContext) -> None:
        image_path = Path(context.image_path)
        target_device_id = context.target_device_id or ""

        try:
            image_size = image_path.stat().st_size
            if image_size <= 0:
                raise RuntimeError("The selected image file is empty.")

            target_size = get_physical_drive_size_bytes(target_device_id)
            if target_size is None:
                raise RuntimeError(
                    "Could not determine the size of the selected target device. "
                    "Run the app as Administrator and try again."
                )

            if image_size > target_size:
                raise RuntimeError("The selected image is larger than the target device.")

            step_definitions = self.backend.get_operation_steps("verify")
        except Exception as exc:
            QMessageBox.critical(self, "Cannot start verify", str(exc))
            self._log(f"Verify preparation failed: {exc}")
            return

        self.controller.start_operation("verify", step_definitions)
        self.controller.set_running_step(1)
        self.active_operation = "verify"
        self.active_context = context
        self.active_source_label = ""
        self.active_target_label = self._selected_disk_label()
        self.copy_cancel_requested = False
        self.active_copy_mode = "verify"
        self.active_copy_output_path = None
        self.active_copy_target_device_id = target_device_id
        self.progress_bar.setValue(0)
        self._refresh_queue()
        self._refresh_action_button_states()

        self._log(f"Prepared real verify against: {target_device_id}")
        self._log(f"Selected target device: {self.active_target_label}")
        self._log(f"Verify source image: {image_path}")
        self._log(f"Image size to compare: {format_bytes(image_size)}")
        self._log(f"Target size: {format_bytes(target_size)}")
        self._set_status("Starting image verification against SD card...")

        try:
            self.controller.set_running_step(2)
            self._refresh_queue()

            bytes_verified = compare_image_to_physical_drive(
                image_path,
                target_device_id,
                progress_callback=self._on_real_verify_progress,
                cancel_callback=lambda: self.copy_cancel_requested,
            )

            self.controller.set_running_step(3)
            self._refresh_queue()

            if bytes_verified != image_size:
                raise RuntimeError("Verify completed with an unexpected byte count.")

            self.controller.complete_operation()
            self.progress_bar.setValue(100)
            self._refresh_queue()
            self._set_status(f"Verified image against SD card successfully. {format_bytes(bytes_verified)}")
            self._log(f"Completed real verify operation against: {target_device_id}")
            self._record_recent_job("Completed", "verify")
        except CopyCancelledError:
            self.controller.fail_operation()
            self._refresh_queue()
            self.progress_bar.setValue(0)
            self._set_status("Cancelled 'verify'.")
            self._log("Cancelled real verify operation.")
            self._record_recent_job("Cancelled", "verify")
        except Exception as exc:
            self.controller.fail_operation()
            self._refresh_queue()
            self.progress_bar.setValue(0)
            self._set_status("Verify failed.")
            self._log(f"Real verify failed: {exc}")
            self._record_recent_job("Failed", "verify")
            QMessageBox.critical(
                self,
                "Verify failed",
                f"The selected image does not match the selected SD card:\n{exc}",
            )
        finally:
            self.copy_cancel_requested = False
            self._clear_active_operation_state()
            self._refresh_action_button_states()

    def _start_real_shrink_operation(self, context: OperationContext) -> None:
        self._refresh_shrink_readiness(log_result=True)

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

        if not self.shrink_ready:
            report = self.shrink_availability_report or get_shrink_availability_report()
            self.shrink_availability_report = report
            QMessageBox.critical(
                self,
                "PiShrink not available",
                f"Shrink is not ready.\n\nStatus: {report.summary}\n\nDetails: {report.detail}\n\n{report.help_text}",
            )
            self._log(f"Shrink blocked because WSL PiShrink was not available: {report.summary}")
            return

        try:
            plan = build_pishrink_plan(context.image_path)
            step_definitions = self.backend.get_operation_steps("shrink")
            source_size = image_path.stat().st_size
        except ValueError as exc:
            QMessageBox.critical(self, "Cannot prepare shrink", str(exc))
            self._log(f"Shrink preparation failed: {exc}")
            return

        self.controller.start_operation("shrink", step_definitions)
        self.controller.set_running_step(1)
        self.active_operation = "shrink"
        self.active_context = context
        self.active_source_label = ""
        self.active_target_label = ""
        self.active_shrink_plan = plan
        self.active_shrink_source_size = source_size
        self.shrink_progress_value = 15
        self.shrink_final_stage_logged = False
        self.progress_bar.setValue(self.shrink_progress_value)
        self._refresh_queue()
        self._refresh_action_button_states()
        self._set_last_result(
            status="Shrink running...",
            original_size=format_bytes(source_size),
            output_path=plan.output_path_windows,
        )

        self._log(f"Prepared WSL shrink plan for: {plan.image_path_windows}")
        self._log(f"Original image size: {format_bytes(source_size)}")
        self._log(f"Shrink output will be: {plan.output_path_windows}")
        self._log(f"WSL command: {plan.shell_command}")
        self._set_status("Starting WSL shrink. This may take a while for large images...")

        self.active_shrink_process = start_pishrink_process(plan)
        self._start_shrink_output_reader()
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
            self._refresh_action_button_states()
            return

        self.controller.apply_progress(self.progress_value)
        self.progress_bar.setValue(self.progress_value)
        self._refresh_queue()
        self._set_status(f"Running '{self.active_operation}' operation... {self.progress_value}%")

    def _poll_shrink_process(self) -> None:
        if self.active_shrink_process is None:
            self.shrink_poll_timer.stop()
            return

        self._drain_shrink_output_queue()
        returncode = self.active_shrink_process.poll()

        if returncode is None:
            self.shrink_progress_value = min(90, self.shrink_progress_value + 3)
            self.controller.set_running_step(2)
            self.progress_bar.setValue(self.shrink_progress_value)
            self._refresh_queue()

            now = time.monotonic()
            if (
                self.shrink_progress_value >= 90
                and self.shrink_last_output_monotonic > 0
                and (now - self.shrink_last_output_monotonic) >= 120
                and (now - self.shrink_last_stall_notice_monotonic) >= 120
            ):
                self._log("PiShrink has produced no new output for at least 2 minutes, but the process is still running.")
                self.shrink_last_stall_notice_monotonic = now

            if self.shrink_progress_value >= 90:
                self._set_status("Finishing shrink and truncating image... this can sit near 90% for a while.")
                if not self.shrink_final_stage_logged:
                    self._log(
                        "Shrink has reached the final stage. It may sit near 90% while PiShrink finishes filesystem work and truncates the image."
                    )
                    self.shrink_final_stage_logged = True
            else:
                self._set_status(
                    f"Shrinking image in WSL... {self.shrink_progress_value}% "
                    f"(large images can take quite a while)"
                )
            return

        self.shrink_poll_timer.stop()
        self._finalize_shrink_output_reader()
        plan = self.active_shrink_plan
        completed_name = self.active_operation or "shrink"

        if returncode == 0:
            self.controller.set_running_step(3)
            self.progress_bar.setValue(95)
            self._refresh_queue()
            self.controller.complete_operation()
            self.progress_bar.setValue(100)
            self._refresh_queue()

            output_size_text = "-"
            saved_text = "-"
            status_text = "Shrink completed successfully."
            output_path_text = plan.output_path_windows if plan is not None else "-"

            if plan is not None:
                output_path = Path(plan.output_path_windows)
                if output_path.exists() and output_path.is_file():
                    output_size = output_path.stat().st_size
                    output_size_text = format_bytes(output_size)

                    if self.active_shrink_source_size is not None:
                        saved_text = describe_reduction(self.active_shrink_source_size, output_size)
                        status_text = f"Shrink completed successfully. {saved_text}"

                    record_import_metadata(
                        self.vault_path,
                        output_path.name,
                        is_shrunk=True,
                        original_filename=Path(self.active_context.image_path).name if self.active_context else output_path.name,
                    )

                    self._log(f"Shrunk image size: {output_size_text}")

                    if (
                        self.delete_source_after_successful_shrink is not None
                        and self.delete_source_after_successful_shrink.exists()
                    ):
                        cleanup_source = self.delete_source_after_successful_shrink
                        try:
                            if cleanup_source.resolve() != output_path.resolve():
                                cleanup_source.unlink()
                                self._log(
                                    f"Removed temporary unshrunk image after successful shrink: {cleanup_source}"
                                )
                        except OSError as exc:
                            self._log(f"Could not remove temporary unshrunk image: {exc}")

            self._set_last_result(
                status=status_text,
                original_size=format_bytes(self.active_shrink_source_size) if self.active_shrink_source_size is not None else "-",
                output_size=output_size_text,
                saved=saved_text,
                output_path=output_path_text,
            )

            self._set_status(status_text)
            self._log(f"Completed real WSL shrink operation: {completed_name}")
            if plan is not None:
                self._log(f"Shrink output image: {plan.output_path_windows}")
            if saved_text != "-":
                self._log(saved_text)
            self._record_recent_job("Completed", completed_name)
            if plan is not None:
                self._refresh_vault(select_path=Path(plan.output_path_windows))
        else:
            self._remove_incomplete_shrink_output(log_prefix="Shrink failure")
            self.controller.fail_operation()
            self._refresh_queue()
            self._set_status("Shrink failed.")
            self._set_last_result(
                status="Shrink failed.",
                original_size=format_bytes(self.active_shrink_source_size) if self.active_shrink_source_size is not None else "-",
                output_path=plan.output_path_windows if plan is not None else "-",
            )
            self._log(f"WSL shrink failed with return code {returncode}.")
            self._record_recent_job("Failed", completed_name)
            self._refresh_vault()
            QMessageBox.critical(
                self,
                "Shrink failed",
                "PiShrink reported an error. Review the Activity Log for details.",
            )

        self._clear_active_operation_state()
        self._refresh_action_button_states()

    def _cancel_operation(self) -> None:
        if self.active_copy_mode in {"save", "write", "verify"}:
            self.copy_cancel_requested = True
            self._set_status(f"Cancelling '{self.active_copy_mode}'...")
            self._log(f"Cancellation requested for real {self.active_copy_mode} operation.")
            return

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
            self._refresh_action_button_states()
            return

        if self.shrink_poll_timer.isActive() and self.active_shrink_process is not None:
            self.shrink_poll_timer.stop()
            failed_name = self.active_operation or "shrink"
            self._log("Cancellation requested for WSL shrink process.")
            self._terminate_process(self.active_shrink_process)
            self._finalize_shrink_output_reader()

            self._remove_incomplete_shrink_output(log_prefix="Shrink cancellation")
            self.controller.fail_operation()
            self._refresh_queue()
            self._set_status(f"Cancelled '{failed_name}'.")
            self._set_last_result(
                status="Shrink cancelled." if failed_name == "shrink" else f"{failed_name} cancelled.",
                original_size=format_bytes(self.active_shrink_source_size) if self.active_shrink_source_size is not None else "-",
                output_path=self.active_shrink_plan.output_path_windows if self.active_shrink_plan is not None else "-",
            )
            self._log(f"Cancelled real WSL shrink operation: {failed_name}")
            self.progress_bar.setValue(0)
            self._record_recent_job("Cancelled", failed_name)
            self._refresh_vault()
            self._clear_active_operation_state()
            self._refresh_action_button_states()
            return

        self._log("Cancel requested, but no operation was active.")
        self._set_status("No active operation to cancel.")

    def _cancel_operation_for_close(self) -> None:
        if self.active_shrink_process is not None:
            failed_name = self.active_operation or "shrink"
            self._log("Closing app: cancelling active WSL shrink process.")
            self.shrink_poll_timer.stop()
            self._terminate_process(self.active_shrink_process)
            self._finalize_shrink_output_reader()

            self._remove_incomplete_shrink_output(log_prefix="App close cancellation")
            self.controller.fail_operation()
            self._refresh_queue()
            self._set_status(f"Cancelled '{failed_name}' due to app close.")
            self._set_last_result(
                status="Shrink cancelled due to app close.",
                original_size=format_bytes(self.active_shrink_source_size) if self.active_shrink_source_size is not None else "-",
                output_path=self.active_shrink_plan.output_path_windows if self.active_shrink_plan is not None else "-",
            )
            self.progress_bar.setValue(0)
            self._record_recent_job("Cancelled", failed_name)
            self._clear_active_operation_state()
            self._refresh_action_button_states()
            return

        if self.active_operation is not None or self.timer.isActive():
            failed_name = self.active_operation or "operation"
            self._log(f"Closing app: cancelling active '{failed_name}' operation.")
            self.timer.stop()
            self.controller.fail_operation()
            self._refresh_queue()
            self._set_status(f"Cancelled '{failed_name}' due to app close.")
            self.progress_bar.setValue(0)
            self._record_recent_job("Cancelled", failed_name)
            self._clear_active_operation_state()
            self._refresh_action_button_states()
            return

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
        self.active_shrink_source_size = None
        self.progress_value = 0
        self.shrink_progress_value = 0
        self.shrink_final_stage_logged = False
        self.delete_source_after_successful_shrink = None
        self.shrink_output_queue = None
        self.shrink_output_thread = None
        self.shrink_last_output_monotonic = 0.0
        self.shrink_last_stall_notice_monotonic = 0.0
        self.active_copy_mode = None
        self.active_copy_output_path = None
        self.active_copy_target_device_id = None

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
