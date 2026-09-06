"""Main window for the mtapy GUI receiver."""

import os
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .worker import ReceiverWorker


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("mtapy 互传接收端")
        self.resize(640, 480)

        self.worker = ReceiverWorker()
        self._connect_worker_signals()

        self._build_ui()
        self._build_tray()

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        central = QWidget()
        layout = QVBoxLayout(central)

        # --- Settings group ---
        settings = QGroupBox("设置")
        s_layout = QVBoxLayout(settings)

        name_row = QHBoxLayout()
        name_row.addWidget(QLabel("设备名:"))
        self.name_edit = QLineEdit("Ubuntu-PC")
        name_row.addWidget(self.name_edit)
        s_layout.addLayout(name_row)

        dir_row = QHBoxLayout()
        dir_row.addWidget(QLabel("保存到:"))
        self.dir_edit = QLineEdit(str(Path.home() / "Downloads"))
        self.dir_edit.setReadOnly(True)
        self.dir_btn = QPushButton("选择...")
        self.dir_btn.clicked.connect(self._choose_dir)
        dir_row.addWidget(self.dir_edit, 1)
        dir_row.addWidget(self.dir_btn)
        s_layout.addLayout(dir_row)

        self.auto_accept_check = QCheckBox("自动接受文件")
        self.auto_accept_check.setChecked(True)
        s_layout.addWidget(self.auto_accept_check)

        layout.addWidget(settings)

        # --- Control buttons ---
        btn_row = QHBoxLayout()
        self.start_btn = QPushButton("开始监听")
        self.start_btn.clicked.connect(self._on_start)
        self.stop_btn = QPushButton("停止")
        self.stop_btn.clicked.connect(self._on_stop)
        self.stop_btn.setEnabled(False)
        btn_row.addWidget(self.start_btn)
        btn_row.addWidget(self.stop_btn)
        layout.addLayout(btn_row)

        # --- Status ---
        self.status_label = QLabel("未启动")
        self.status_label.setStyleSheet("font-weight: bold;")
        layout.addWidget(self.status_label)

        # --- Files table ---
        files_group = QGroupBox("收到的文件")
        f_layout = QVBoxLayout(files_group)
        self.files_table = QTableWidget(0, 3)
        self.files_table.setHorizontalHeaderLabels(["文件名", "大小", "时间"])
        self.files_table.horizontalHeader().setStretchLastSection(True)
        self.files_table.setColumnWidth(0, 360)
        self.files_table.setColumnWidth(1, 90)
        self.files_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.files_table.cellDoubleClicked.connect(self._open_file)
        f_layout.addWidget(self.files_table)
        layout.addWidget(files_group, 1)

        self.setCentralWidget(central)

    def _build_tray(self) -> None:
        self.tray = _TrayIcon(self)
        self.tray.show()

    # ------------------------------------------------------------------
    # Worker signal handlers
    # ------------------------------------------------------------------

    def _connect_worker_signals(self) -> None:
        self.worker.status.connect(self._on_status)
        self.worker.transfer_started.connect(self._on_transfer_started)
        self.worker.file_received.connect(self._on_file_received)
        self.worker.p2p.connect(self._on_p2p)
        self.worker.error.connect(self._on_error)
        self.worker.finished.connect(self._on_finished)

    def _on_status(self, message: str) -> None:
        self.status_label.setText(message)
        self.tray.showMessage("mtapy", message, QIcon(), 3000)

    def _on_transfer_started(self, sender: str, filename: str, size: int) -> None:
        self.status_label.setText(f"📥 {sender} → {filename} ({size} bytes)")

    def _on_file_received(self, name: str, path: str, size: int) -> None:
        row = self.files_table.rowCount()
        self.files_table.insertRow(row)
        self.files_table.setItem(row, 0, QTableWidgetItem(name))
        self.files_table.setItem(row, 1, QTableWidgetItem(_fmt_size(size)))
        self.files_table.setItem(row, 2, QTableWidgetItem(_fmt_time(path)))
        self.files_table.scrollToBottom()
        self.tray.showMessage("收到文件", f"{name} ({_fmt_size(size)})", QIcon(), 5000)

    def _on_p2p(self, ssid: str, psk: str, port: int) -> None:
        self.status_label.setText(f"📶 收到 P2P 信息：{ssid}")

    def _on_error(self, message: str) -> None:
        self.status_label.setText(f"❌ {message}")
        self.tray.showMessage("mtapy 错误", message, QIcon(), 5000)

    def _on_finished(self) -> None:
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.status_label.setText("已停止")

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def _on_start(self) -> None:
        out_dir = self.dir_edit.text().strip() or str(Path.home() / "Downloads")
        Path(out_dir).mkdir(parents=True, exist_ok=True)
        self.worker.start(
            device_name=self.name_edit.text().strip(),
            output_dir=out_dir,
            auto_accept=self.auto_accept_check.isChecked(),
        )
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.status_label.setText("启动中 ...")

    def _on_stop(self) -> None:
        self.worker.stop()

    def _choose_dir(self) -> None:
        path = QFileDialog.getExistingDirectory(
            self, "选择保存目录", self.dir_edit.text()
        )
        if path:
            self.dir_edit.setText(path)

    def _open_file(self, row: int, _col: int) -> None:
        item = self.files_table.item(row, 0)
        if item is None:
            return
        name = item.text()
        directory = self.dir_edit.text()
        # Find the file (name may have a _N suffix from conflict handling).
        candidates = list(Path(directory).glob(f"{name}*"))
        if candidates:
            os.system(f'xdg-open "{candidates[0]}" >/dev/null 2>&1 &')

    def closeEvent(self, event) -> None:  # noqa: N802
        if self.worker.is_running():
            reply = QMessageBox.question(
                self,
                "退出",
                "接收端仍在运行，确定退出吗？",
                QMessageBox.Yes | QMessageBox.No,
            )
            if reply != QMessageBox.Yes:
                event.ignore()
                return
            self.worker.stop()
        event.accept()


class _TrayIcon:
    """System tray icon with a context menu."""

    def __init__(self, window: MainWindow) -> None:
        from PySide6.QtWidgets import QMenu, QSystemTrayIcon

        self._tray = QSystemTrayIcon(QIcon(), window)
        self._tray.setToolTip("mtapy 互传接收端")

        menu = QMenu()
        show_action = menu.addAction("显示窗口")
        show_action.triggered.connect(lambda: window.showNormal())
        menu.addSeparator()
        quit_action = menu.addAction("退出")
        quit_action.triggered.connect(window.close)

        self._tray.setContextMenu(menu)
        self._tray.activated.connect(
            lambda reason: window.showNormal() if reason == 3 else None
        )

    def show(self) -> None:
        self._tray.show()

    def showMessage(self, title: str, message: str, icon: QIcon, ms: int) -> None:
        self._tray.showMessage(title, message, icon, ms)


def _fmt_size(size: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024:
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


def _fmt_time(path: str) -> str:
    from datetime import datetime

    try:
        ts = os.path.getmtime(path)
        return datetime.fromtimestamp(ts).strftime("%H:%M:%S")
    except OSError:
        return ""