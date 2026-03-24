from __future__ import annotations

from datetime import datetime
from pathlib import Path
import subprocess
from shutil import copystat, disk_usage

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtWidgets import (
    QApplication,
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
    QProgressDialog,
    QPushButton,
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
        self.resize(1180, 700)

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

        self.vault_path = default_vault_path()
        self.vault_images: list[VaultImage] = []

        self._build_ui()
        self._load_devices()
        self._refresh_vault()
        self._log("Mock backend is enabled for save/write/verify. Shrink can run in real WSL mode.")
        self._log(f"Image vault folder: {self.vault_path}")
        self._set_status("Ready. Safe mock backend active.")

    def _build_ui(self) -> None:
        central = QWidget(self)
        self.setCentralWidget(central)

        root = QVBoxLayout(central)
        root.setSpacing(10)

        top_notice = QLabel(
            "This build is intentionally non-destructive for disk access. "
            "Save, Write, and Verify are mocked. Shrink can run through WSL PiShrink."
        )
        top_notice.setWordWrap(True)
        root.addWidget(top_notice)

        main_row = QHBoxLayout()

        main_row.addWidget(self._build_vault_group(), 1)

        right_column = QVBoxLayout()

        upper_right = QHBoxLayout()
        upper_right.addWidget(self._build_sources_group(), 3)
        upper_right.addWidget(self._build_actions_group(), 2)
        right_column.addLayout(upper_right)

        status_row = QHBoxLayout()

        status_left_column = QVBoxLayout()

        progress_group = QGroupBox("Current Status")
        progress_layout = QVBoxLayout(progress_group)
        self.status_label = QLabel("Ready.")
        self.status_label.setWordWrap(True)
        progress_layout.addWidget(self.status_label)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        progress_layout.addWidget(self.progress_bar)

        status_left_column.addWidget(progress_group)
        status_left_column.addWidget(self._build_drive_group())

        status_row.addLayout(status_left_column, 2)
        status_row.addWidget(self._build_last_result_group(), 1)
        right_column.addLayout(status_row)

        main_row.addLayout(right_column, 3)

        root.addLayout(main_row, 2)

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
        self.image_path_edit = QLineEdit("")
        self.image_path_edit.setPlaceholderText("Select or browse to an image file (.img)")
        layout.addWidget(self.image_path_edit, 2, 1)

        browse_btn = QPushButton("Browse...")
        browse_btn.clicked.connect(self._browse_image_path)
        layout.addWidget(browse_btn, 2, 2)

        refresh_btn = QPushButton("Refresh Device List")
        refresh_btn.clicked.connect(self._load_devices)
        layout.addWidget(refresh_btn, 3, 1)

        return group

    def _build_vault_group(self) -> QGroupBox:
        group = QGroupBox("Vault Images")
        layout = QVBoxLayout(group)

        path_label = QLabel(f"Stored with the app in:\n{self.vault_path}")
        path_label.setWordWrap(True)
        layout.addWidget(path_label)

        toolbar = QHBoxLayout()

        import_btn = QPushButton("Import Image")
        import_btn.clicked.connect(self._import_image_into_vault)
        toolbar.addWidget(import_btn)

        self.delete_vault_btn = QPushButton("Delete Selected")
        self.delete_vault_btn.clicked.connect(self._delete_selected_vault_image)
        self.delete_vault_btn.setEnabled(False)
        toolbar.addWidget(self.delete_vault_btn)

        refresh_btn = QPushButton("Refresh Vault")
        refresh_btn.clicked.connect(self._refresh_vault)
        toolbar.addWidget(refresh_btn)

        toolbar.addStretch(1)
        layout.addLayout(toolbar)

        self.vault_list = QListWidget()
        self.vault_list.itemSelectionChanged.connect(self._on_vault_selection_changed)
        self.vault_list.setMinimumWidth(285)
        self.vault_list.setMinimumHeight(0)
        self.vault_list.setWordWrap(True)
        self.vault_list.setSpacing(4)
        layout.addWidget(self.vault_list, 1)

        self.vault_summary_label = QLabel("No images found in vault.")
        self.vault_summary_label.setWordWrap(True)
        layout.addWidget(self.vault_summary_label, 0)

        return group

    def _build_actions_group(self) -> QGroupBox:
        group = QGroupBox("Actions")
        layout = QVBoxLayout(group)

        self.write_btn = QPushButton("Write Image to SD Card")
        self.write_btn.clicked.connect(lambda: self._start_operation("write"))
        layout.addWidget(self.write_btn)

        self.save_btn = QPushButton("Save SD Card to Image")
        self.save_btn.clicked.connect(lambda: self._start_operation("save"))
        layout.addWidget(self.save_btn)

        self.shrink_btn = QPushButton("Shrink Existing Image")
        self.shrink_btn.clicked.connect(lambda: self._start_operation("shrink"))
        layout.addWidget(self.shrink_btn)

        self.verify_btn = QPushButton("Verify Last Write")
        self.verify_btn.clicked.connect(lambda: self._start_operation("verify"))
        layout.addWidget(self.verify_btn)

        self.cancel_btn = QPushButton("Cancel Current Task")
        self.cancel_btn.clicked.connect(self._cancel_operation)
        layout.addWidget(self.cancel_btn)

        layout.addStretch(1)
        return group

    def _build_drive_group(self) -> QGroupBox:
        group = QGroupBox("Tool Drive Status")
        layout = QVBoxLayout(group)

        self.drive_size_value = QLabel("Drive Size: -")
        self.drive_size_value.setWordWrap(True)
        layout.addWidget(self.drive_size_value)

        self.drive_free_value = QLabel("Drive Free Space: -")
        self.drive_free_value.setWordWrap(True)
        layout.addWidget(self.drive_free_value)

        self.vault_size_value = QLabel("Vault Size: -")
        self.vault_size_value.setWordWrap(True)
        layout.addWidget(self.vault_size_value)

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
            "Completed, failed, and cancelled operations appear here with the device selections and image path used."
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

    def _build_last_result_group(self) -> QGroupBox:
        group = QGroupBox("Last Shrink Result")
        layout = QGridLayout(group)

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

        return group

    def _set_last_result(
        self,
        *,
        status: str,
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

    def _browse_image_path(self) -> None:
        filename, _ = QFileDialog.getOpenFileName(
            self,
            "Choose image file",
            self.image_path_edit.text() or str(self.vault_path),
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

    def _refresh_drive_status(self) -> None:
        try:
            usage_target = self.vault_path if self.vault_path.exists() else self.vault_path.parent
            usage = disk_usage(usage_target)
            vault_size = sum(image.size_bytes for image in self.vault_images)

            self.drive_size_value.setText(f"Drive Size: {format_bytes(usage.total)}")
            self.drive_free_value.setText(f"Drive Free Space: {format_bytes(usage.free)}")
            self.vault_size_value.setText(f"Vault Size: {format_bytes(vault_size)}")
        except OSError as exc:
            self.drive_size_value.setText("Drive Size: Unavailable")
            self.drive_free_value.setText("Drive Free Space: Unavailable")
            self.vault_size_value.setText("Vault Size: Unavailable")
            self._log(f"Could not read tool drive status: {exc}")

    def _refresh_vault(self, *, select_path: Path | None = None) -> None:
        self.vault_images = scan_vault(self.vault_path)
        self.vault_list.clear()
        self.delete_vault_btn.setEnabled(False)

        for image in self.vault_images:
            line1 = image.filename
            line2 = f"{image.formatted_size} | {image.formatted_modified} | {image.status_text}"
            text = f"{line1}\n{line2}"

            item = QListWidgetItem(text)
            item.setData(256, str(image.path))
            item.setSizeHint(QSize(item.sizeHint().width(), item.sizeHint().height() + 12))

            tooltip_lines = [
                f"Path: {image.path}",
                f"Size: {image.formatted_size}",
                f"Modified: {image.formatted_modified}",
                f"Status: {image.status_text}",
            ]
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

        if select_path is not None:
            select_text = str(select_path)
            for index in range(self.vault_list.count()):
                item = self.vault_list.item(index)
                if item.data(256) == select_text:
                    self.vault_list.setCurrentItem(item)
                    break

        self._refresh_drive_status()
        self._log(f"Vault refreshed. Found {count} image(s).")

    def _get_selected_vault_path(self) -> Path | None:
        item = self.vault_list.currentItem()
        if item is None:
            return None

        image_path = item.data(256)
        if not image_path:
            return None

        return Path(image_path)

    def _on_vault_selection_changed(self) -> None:
        selected_path = self._get_selected_vault_path()
        self.delete_vault_btn.setEnabled(selected_path is not None)

        if selected_path is None:
            return

        self.image_path_edit.setText(str(selected_path))
        self._log(f"Selected vault image: {selected_path}")

    def _delete_selected_vault_image(self) -> None:
        selected_path = self._get_selected_vault_path()
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
            if self.image_path_edit.text().strip() == str(selected_path):
                self.image_path_edit.clear()
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
            self.image_path_edit.setText(str(target_path))
            self._log(f"Imported image into vault: {target_path}")
            self._set_status("Import completed.")

            if shrink_after_import:
                self.delete_source_after_successful_shrink = target_path
                self._start_operation("shrink")
        except OSError as exc:
            QMessageBox.critical(self, "Import failed", f"Could not import image: {exc}")
            self._log(f"Import failed: {exc}")
            self._set_status("Import failed.")

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
            source_size = image_path.stat().st_size
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
        self.active_shrink_source_size = source_size
        self.shrink_progress_value = 15
        self.shrink_final_stage_logged = False
        self.progress_bar.setValue(self.shrink_progress_value)
        self._refresh_queue()
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

            if self.shrink_progress_value >= 90:
                self._set_status("Finishing shrink and truncating image... this can sit near 90% for a while.")
                if not self.shrink_final_stage_logged:
                    self._log("Shrink has reached the final stage. It may sit near 90% while PiShrink finishes filesystem work and truncates the image.")
                    self.shrink_final_stage_logged = True
            else:
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
                                self._log(f"Removed temporary unshrunk import after successful shrink: {cleanup_source}")
                        except OSError as exc:
                            self._log(f"Could not remove temporary unshrunk import: {exc}")

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
            if stdout.strip():
                self._log("PiShrink output:")
                self._log(stdout.strip())
            self._record_recent_job("Completed", completed_name)
            if plan is not None:
                self._refresh_vault(select_path=Path(plan.output_path_windows))
                self.image_path_edit.setText(plan.output_path_windows)
        else:
            self.controller.fail_operation()
            self._refresh_queue()
            self._set_status("Shrink failed.")
            self._set_last_result(
                status="Shrink failed.",
                original_size=format_bytes(self.active_shrink_source_size) if self.active_shrink_source_size is not None else "-",
                output_path=plan.output_path_windows if plan is not None else "-",
            )
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
            self._set_last_result(
                status="Shrink cancelled." if failed_name == "shrink" else f"{failed_name} cancelled.",
                original_size=format_bytes(self.active_shrink_source_size) if self.active_shrink_source_size is not None else "-",
                output_path=self.active_shrink_plan.output_path_windows if self.active_shrink_plan is not None else "-",
            )
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
        self.active_shrink_source_size = None
        self.progress_value = 0
        self.shrink_progress_value = 0
        self.shrink_final_stage_logged = False
        self.delete_source_after_successful_shrink = None

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
