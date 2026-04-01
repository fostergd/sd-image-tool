from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication, QMessageBox

from sdtool.ui.main_window import MainWindow
from sdtool.windows_elevation import ensure_admin_or_relaunch, is_current_process_elevated


def main(argv: list[str] | None = None) -> int:
    actual_argv = list(argv if argv is not None else sys.argv[1:])

    continue_launch, detail = ensure_admin_or_relaunch(actual_argv)
    if not continue_launch and not is_current_process_elevated():
        if detail != "Started elevated instance.":
            app = QApplication.instance() or QApplication(sys.argv)
            QMessageBox.critical(
                None,
                "Administrator access required",
                "SD Image Tool must run with administrator rights.\n\n"
                f"{detail}",
            )
            return 1
        return 0

    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
