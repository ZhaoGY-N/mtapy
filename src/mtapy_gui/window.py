"""Main window for the mtapy GUI receiver."""

import os
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from . import theme
from .steps import StepIndicator
from .worker import (
    ReceiverWorker,
    STAGE_IDLE,
    STAGE_LISTENING,
    STAGE_P2P,
    STAGE_WIFI,
    STAGE_TRANSFER,
    STAGE_DONE,
    STAGE_NAMES,
)

# Order shown in the step indicator.
_STEPS = [
    (STAGE_LISTENING, "广播监听"),
    (STAGE_P2P, "配对"),
    (STAGE_WIFI, "Wi-Fi"),
    (STAGE_TRANSFER, "传输"),
    (STAGE_DONE, "完成"),
]


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("mtapy 互传接收端")
        self.resize(680, 540)

        self.dark = False
        self.worker = ReceiverWorker()
        self._connect_worker_signals()

        self._build_ui()
        self._build_tray()
        self._apply_theme()

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        central = QWidget()
        central.setObjectName("central")
        layout = QVBoxLayout(central)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(12)

        # --- Title ---
        title_row = QHBoxLayout()
        title = QLabel("mtapy")
        title.setStyleSheet("font-size: 18px; font-weight: 700;")
        self.stage_hint = QLabel("等待开始")
        self.stage_hint.setObjectName("dim")
        title_row.addWidget(title)
        title_row.addStretch()
        title_row.addWidget(self.stage_hint)
        layout.addLayout(title_row)

        # --- Step indicator + download progress ---
        self.steps = StepIndicator(_STEPS)
        self.steps.set_current_step(STAGE_IDLE)
        layout.addWidget(self.steps)

        prog_row = QHBoxLayout()
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        self.progress_label = QLabel("")
        self.progress_label.setObjectName("dim")
        prog_row.addWidget(self.progress_bar, 1)
        prog_row.addWidget(self.progress_label)
        layout.addLayout(prog_row)

        # --- Settings group ---
        settings = QGroupBox("设置")
        s_layout = QVBoxLayout(settings)

        name_row = QHBoxLayout()
        name_row.addWidget(QLabel("设备名:"))
        self.name_edit = QLineEdit("Ubuntu-PC")
        name_row.addWidget(self.name_edit, 1)
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

        self.auto_accept_check = QCheckBox("自动接受文件（不询问）")
        self.auto_accept_check.setChecked(True)
        s_layout.addWidget(self.auto_accept_check)

        layout.addWidget(settings)

        # --- Control buttons ---
        btn_row = QHBoxLayout()
        self.start_btn = QPushButton("开始监听")
        self.start_btn.setObjectName("primary")
        self.start_btn.clicked.connect(self._on_start)
        self.stop_btn = QPushButton("停止")
        self.stop_btn.clicked.connect(self._on_stop)
        self.stop_btn.setEnabled(False)
        btn_row.addWidget(self.start_btn)
        btn_row.addWidget(self.stop_btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        # --- Status ---
        self.status_label = QLabel("未启动")
        layout.addWidget(self.status_label)

        # --- Files table ---
        files_group = QGroupBox("收到的文件")
        f_layout = QVBoxLayout(files_group)
        self.files_table = QTableWidget(0, 3)
        self.files_table.setHorizontalHeaderLabels(["文件名", "大小", "时间"])
        self.files_table.horizontalHeader().setStretchLastSection(True)
        self.files_table.setColumnWidth(0, 400)
        self.files_table.setColumnWidth(1, 90)
        self.files_table.setAlternatingRowColors(True)
        self.files_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.files_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.files_table.cellDoubleClicked.connect(self._open_file)
        f_layout.addWidget(self.files_table)
        layout.addWidget(files_group, 1)

        self.setCentralWidget(central)

    def _apply_theme(self) -> None:
        """Detect dark/light and apply the matching stylesheet."""
        self.dark = theme.is_dark_mode()
        style = theme.build_stylesheet(self.dark)
        # Apply to the app instance (not just this window) so dialogs match.
        from PySide6.QtWidgets import QApplication

        QApplication.instance().setStyleSheet(style)
        self.steps.set_dark(self.dark)
        self._restyle_buttons()

    def _build_tray(self) -> None:
        self.tray = _TrayIcon(self)
        self.tray.show()

    def _restyle_buttons(self) -> None:
        c = theme.DARK if self.dark else theme.LIGHT
        self.start_btn.setStyleSheet(
            f"background-color: {c['accent']}; color: #fff; border: none;"
            f"border-radius: 8px; padding: 8px 18px; font-weight: 600;"
        )

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
        self.worker.stage.connect(self._on_stage)
        self.worker.transfer_requested.connect(self._on_transfer_requested)
        self.worker.progress.connect(self._on_progress)

    def _on_status(self, message: str) -> None:
        self.status_label.setText(message)
        self.tray.showMessage("mtapy", message, QIcon(), 3000)

    def _on_transfer_started(self, sender: str, filename: str, size: int) -> None:
        self.status_label.setText(f"📥 {sender} → {filename} ({_fmt_size(size)})")

    def _on_file_received(self, name: str, path: str, size: int) -> None:
        row = self.files_table.rowCount()
        self.files_table.insertRow(row)
        self.files_table.setItem(row, 0, QTableWidgetItem(name))
        self.files_table.setItem(row, 1, QTableWidgetItem(_fmt_size(size)))
        self.files_table.setItem(row, 2, QTableWidgetItem(_fmt_time(path)))
        self.files_table.scrollToBottom()
        self.tray.showMessage("收到文件", f"{name} ({_fmt_size(size)})", QIcon(), 5000)

    def _on_p2p(self, ssid: str, psk: str, port: int) -> None:
        self.stage_hint.setText(f"已配对 {ssid}")

    def _on_error(self, message: str) -> None:
        self.status_label.setText(f"❌ {message}")
        self.tray.showMessage("mtapy 错误", message, QIcon(), 5000)

    def _on_finished(self) -> None:
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.status_label.setText("已停止")

    def _on_stage(self, stage_id: int, label: str) -> None:
        self.steps.set_current_step(stage_id)
        if stage_id != STAGE_TRANSFER:
            self.stage_hint.setText(STAGE_NAMES.get(stage_id, label))

    def _on_transfer_requested(self, sender: str, filename: str, size: int) -> None:
        """Ask the user whether to accept an incoming transfer."""
        self.status_label.setText(f"📥 {sender} 想发送 {filename} ...")
        box = QMessageBox(self)
        box.setWindowTitle("接收文件")
        box.setIcon(QMessageBox.Icon.Question)
        box.setText(f"**{sender}** 想发送一个文件")
        box.setInformativeText(
            f"文件名：{filename}\n大小：{_fmt_size(size)}\n是否接收？"
        )
        accept_btn = box.addButton("接收", QMessageBox.ButtonRole.AcceptRole)
        reject_btn = box.addButton("拒绝", QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(accept_btn)
        box.exec()
        accepted = box.clickedButton() is accept_btn
        self.worker.set_decision(accepted)
        self.status_label.setText("已接收，开始下载 ..." if accepted else "已拒绝传输")

    def _on_progress(self, received: int, total: int) -> None:
        if total and total > 0:
            pct = min(int(received * 100 / total), 100)
            self.progress_bar.setRange(0, 100)
            self.progress_bar.setValue(pct)
            self.progress_label.setText(
                f"{_fmt_size(received)} / {_fmt_size(total)}"
            )
        else:
            # Unknown total → indeterminate.
            self.progress_bar.setRange(0, 0)
            self.progress_label.setText(_fmt_size(received))

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
        self.progress_bar.setRange(0, 0)  # indeterminate while starting
        self.progress_label.setText("")

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
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
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
