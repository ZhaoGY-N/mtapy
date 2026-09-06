"""MTA receiver worker: runs the asyncio receiver in a background QThread."""

import asyncio
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QObject, QThread, Signal

from mtapy import MTAReceiver, SendRequest, P2pInfo
from mtapy.drivers.linux import BlueZBLEProvider
from mtapy.wifi_helper import connect_to_wifi


class ReceiverWorker(QObject):
    """Owns the asyncio event loop and the MTA receiver.

    Lives in a dedicated QThread; the GUI talks to it through signals.
    """

    # (message)
    status = Signal(str)
    # (sender_name, file_name, total_size)
    transfer_started = Signal(str, str, int)
    # (file_name, file_path, size)
    file_received = Signal(str, str, int)
    # (ssid, psk, port)
    p2p = Signal(str, str, int)
    # (message)
    error = Signal(str)
    finished = Signal()

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

        async def on_request(request: SendRequest) -> bool:
            self.transfer_started.emit(
                request.sender_name, request.file_name, request.total_size
            )
            return self._auto_accept

        async def on_text(text: str) -> None:
            self.status.emit(f"[TEXT] {text}")

        async def on_p2p(p2p: P2pInfo) -> None:
            self.p2p.emit(p2p.ssid, p2p.psk, p2p.port)
            self.status.emit(f"[WIFI] 连接 {p2p.ssid} ...")
            try:
                success = await asyncio.get_event_loop().run_in_executor(
                    None,
                    lambda: connect_to_wifi(p2p.ssid, p2p.psk, p2p.mac, p2p.freq),
                )
            except Exception as e:
                self.error.emit(f"[WIFI] 连接异常: {e}")
                success = False
            if success:
                self.status.emit("[WIFI] 已连接，等待传输 ...")
                await asyncio.sleep(2.0)
            else:
                self.status.emit("[WIFI] 连接失败，请手动连接")

        receiver = MTAReceiver(
            output_dir=output_dir,
            on_request=on_request,
            on_text=on_text,
        )

        while self._running:
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

            if files:
                for f in files:
                    self.file_received.emit(f.name, str(f.path), f.size)
                self.status.emit(f"[RECV] 收到 {len(files)} 个文件")
            else:
                self.status.emit("[RECV] 会话结束，继续监听 ...")

        self.status.emit("[RECV] 已停止")