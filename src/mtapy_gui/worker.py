"""MTA receiver worker: runs the asyncio receiver in a background QThread."""

import asyncio
import logging
import threading
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QObject, QThread, Signal

from mtapy import MTAReceiver, SendRequest, P2pInfo
from mtapy.drivers.linux import BlueZBLEProvider
from mtapy.wifi_helper import connect_to_wifi, restore_wifi

# Transfer pipeline stages (shared with the GUI's step indicator).
STAGE_IDLE = 0       # stopped / not listening
STAGE_LISTENING = 1  # advertising + GATT ready, waiting for a phone
STAGE_P2P = 2        # P2P credentials received, joining WiFi
STAGE_WIFI = 3       # connected to the phone's group, waiting for data
STAGE_TRANSFER = 4   # transfer in progress (download)
STAGE_DONE = 5       # session finished

STAGE_NAMES = {
    STAGE_IDLE: "待机",
    STAGE_LISTENING: "广播监听",
    STAGE_P2P: "配对",
    STAGE_WIFI: "Wi-Fi 连接",
    STAGE_TRANSFER: "传输中",
    STAGE_DONE: "完成",
}

# File log so a stalled/hung transfer can be diagnosed later (the GUI has no
# scrollback of its own once the worker blocks).
_logger = logging.getLogger("mtapy_gui.worker")
_logger.setLevel(logging.INFO)
if not _logger.handlers:
    _h = logging.FileHandler("/tmp/mtapy_gui.log")
    _h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    _logger.addHandler(_h)
    # Also capture mtapy.transport's [DL] progress so the download stall
    # point is visible in the same file.
    for _name in ("mtapy.transport", "mtapy.wifi_helper", "mtapy"):
        _mlog = logging.getLogger(_name)
        _mlog.setLevel(logging.INFO)
        _mlog.addHandler(_h)


class ReceiverWorker(QObject):
    """Owns the asyncio event loop and the MTA receiver.

    Lives in a dedicated QThread; the GUI talks to it through signals.
    """

    # (message)
    status = Signal(str)
    # (sender_name, file_name, total_size) — qlonglong (64-bit); file sizes can exceed 2GB
    transfer_started = Signal(str, str, 'qlonglong')
    # (file_name, file_path, size)
    file_received = Signal(str, str, 'qlonglong')
    # (ssid, psk, port)
    p2p = Signal(str, str, int)
    # (message)
    error = Signal(str)
    finished = Signal()

    # Pipeline stage: (stage_id, label)
    stage = Signal(int, str)
    # Ask the GUI to accept/reject an incoming transfer: (sender, filename, size)
    transfer_requested = Signal(str, str, 'qlonglong')
    # Download progress: (downloaded_bytes, total_bytes)
    progress = Signal('qlonglong', 'qlonglong')

    def __init__(self) -> None:
        super().__init__()
        self._thread = QThread()
        self.moveToThread(self._thread)

        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._task: Optional[asyncio.Task] = None
        self._running = False

        self._device_name = "Ubuntu-PC"
        self._output_dir = str(Path.home() / "Downloads")
        self._auto_accept = True

        # Accept/reject decision state, written by the GUI thread (via
        # set_decision) and polled by the asyncio worker thread.
        self._decision_lock = threading.Lock()
        self._pending_decision: Optional[bool] = None

    # ------------------------------------------------------------------
    # Public API (called from the GUI thread)
    # ------------------------------------------------------------------

    def start(self, device_name: str, output_dir: str, auto_accept: bool) -> None:
        """Start the receiver thread."""
        if self._running:
            return
        self._device_name = device_name or "Ubuntu-PC"
        self._output_dir = output_dir or str(Path.home() / "Downloads")
        self._auto_accept = auto_accept
        self._running = True
        self._thread.started.connect(self._run_receiver)
        self._thread.start()

    def stop(self) -> None:
        """Stop the receiver thread (cancels the listen task)."""
        self._running = False
        if self._loop is not None and self._task is not None:
            self._loop.call_soon_threadsafe(self._task.cancel)
        self._thread.quit()
        self._thread.wait(5000)

    def is_running(self) -> bool:
        return self._running

    def set_decision(self, accept: bool) -> None:
        """Called from the GUI thread to answer a pending transfer request."""
        with self._decision_lock:
            self._pending_decision = accept

    # ------------------------------------------------------------------
    # Thread body
    # ------------------------------------------------------------------

    def _run_receiver(self) -> None:
        """Runs in the worker thread."""
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._task = self._loop.create_task(self._listen())
        try:
            self._loop.run_until_complete(self._task)
        except asyncio.CancelledError:
            pass
        except Exception as e:  # pragma: no cover
            self.error.emit(str(e))
        finally:
            self._running = False
            self.finished.emit()

    async def _listen(self) -> None:
        """Keep listening for transfers until stopped."""
        ble = BlueZBLEProvider()
        output_dir = Path(self._output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        loop = asyncio.get_event_loop()

        def report_progress(received: int, total: int) -> None:
            # Runs in the download executor thread — hop back to the Qt
            # thread via the signal (thread-safe).
            self.progress.emit(received, total)

        async def on_request(request: SendRequest) -> bool:
            _logger.info(
                "[RECV] %s → %s (%d bytes)",
                request.sender_name, request.file_name, request.total_size,
            )
            self.stage.emit(STAGE_TRANSFER, STAGE_NAMES[STAGE_TRANSFER])
            self.transfer_started.emit(
                request.sender_name, request.file_name, request.total_size
            )
            if self._auto_accept:
                return True
            # Ask the GUI for a decision; poll until the user answers
            # (or 60s timeout → reject).
            with self._decision_lock:
                self._pending_decision = None
            self.transfer_requested.emit(
                request.sender_name, request.file_name, request.total_size
            )
            deadline = loop.time() + 60
            while loop.time() < deadline:
                with self._decision_lock:
                    decision = self._pending_decision
                if decision is not None:
                    return decision
                await asyncio.sleep(0.05)
            _logger.warning("[RECV] Accept decision timed out; rejecting")
            return False

        async def on_text(text: str) -> None:
            self.status.emit(f"[TEXT] {text}")

        async def on_p2p(p2p: P2pInfo) -> None:
            _logger.info("[P2P] SSID=%s port=%s freq=%s", p2p.ssid, p2p.port, p2p.freq)
            self.p2p.emit(p2p.ssid, p2p.psk, p2p.port)
            self.stage.emit(STAGE_P2P, STAGE_NAMES[STAGE_P2P])
            self.status.emit(f"[WIFI] 连接 {p2p.ssid} ...")
            try:
                success = await asyncio.get_event_loop().run_in_executor(
                    None,
                    lambda: connect_to_wifi(p2p.ssid, p2p.psk, p2p.mac, p2p.freq),
                )
            except Exception as e:
                self.error.emit(f"[WIFI] 连接异常: {e}")
                _logger.error("[WIFI] connect error: %s", e)
                success = False
            if success:
                _logger.info("[WIFI] connected to %s", p2p.ssid)
                self.stage.emit(STAGE_WIFI, STAGE_NAMES[STAGE_WIFI])
                self.status.emit("[WIFI] 已连接，等待传输 ...")
                await asyncio.sleep(2.0)
            else:
                self.status.emit("[WIFI] 连接失败，请手动连接")

        receiver = MTAReceiver(
            output_dir=output_dir,
            on_request=on_request,
            on_text=on_text,
            on_progress=report_progress,
        )

        while self._running:
            self.stage.emit(STAGE_LISTENING, STAGE_NAMES[STAGE_LISTENING])
            self.status.emit(
                f"[RECV] 监听中：{self._device_name}（广告 + GATT 就绪）"
            )
            try:
                files = await receiver.listen(
                    device_name=self._device_name,
                    ble_provider=ble,
                    on_p2p=on_p2p,
                    timeout=3600,
                )
            except asyncio.CancelledError:
                raise
            except Exception as e:
                self.error.emit(str(e))
                await asyncio.sleep(3)
                continue
            finally:
                # Restore NetworkManager management after a wpa_supplicant
                # session so the user isn't left without Wi-Fi.
                restore_wifi()

            if files:
                for f in files:
                    self.file_received.emit(f.name, str(f.path), f.size)
                self.stage.emit(STAGE_DONE, STAGE_NAMES[STAGE_DONE])
                self.status.emit(f"[RECV] 收到 {len(files)} 个文件")
            else:
                self.stage.emit(STAGE_LISTENING, STAGE_NAMES[STAGE_LISTENING])
                self.status.emit("[RECV] 会话结束，继续监听 ...")

        self.stage.emit(STAGE_IDLE, STAGE_NAMES[STAGE_IDLE])
        self.status.emit("[RECV] 已停止")