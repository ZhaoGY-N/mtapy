import asyncio
import sys
import os
from pathlib import Path
import argparse
import logging

# Configure logger
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ],
    datefmt='%Y%m%d %H%M%S',
)
logger = logging.getLogger(__name__)

# Add src directory to path so we can import mtapy
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))

from mtapy import MTAReceiver, SendRequest, P2pInfo
from mtapy.drivers.linux import BlueZBLEProvider
from mtapy.wifi_helper import connect_to_wifi


async def listen_for_transfers(
    device_name: str = "Ubuntu-PC",
    timeout: float = 3600.0,
    auto_connect: bool = True,
    full_layout: bool = False,
):
    """Listen for incoming file transfers from an Android 互传 phone."""
    logger.info("[RECV] 📡 Advertising as '%s' | Waiting for Android...", device_name)

    ble = BlueZBLEProvider(full_layout=full_layout)
    output_dir = Path("./received_files")
    output_dir.mkdir(exist_ok=True)

    async def on_request(request: SendRequest) -> bool:
        logger.info(
            "[RECV] 📥 %s -> %s (%s files, %s bytes) | Auto-accepting...",
            request.sender_name, request.file_name, request.file_count, request.total_size,
        )
        return True

    async def on_text(text: str):
        logger.info("[TEXT] 💬 %s", text)

    async def on_p2p(p2p: P2pInfo):
        logger.info("[WIFI] 📶 Connect to SSID: '%s' | PSK: '%s' | PORT: %s", p2p.ssid, p2p.psk, p2p.port)

        if auto_connect:
            logger.info("[WIFI] 🤖 Auto-connecting via nmcli...")
            success = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: connect_to_wifi(p2p.ssid, p2p.psk, p2p.mac),
            )
            if success:
                logger.info("[WIFI] 🚀 Auto-connected! Starting transfer in 2s...")
                await asyncio.sleep(2.0)
                return

        # Manual fallback: ask the user to connect, but don't crash when
        # stdin is unavailable (e.g. running as a background service).
        def wait_input():
            try:
                input("[WIFI] ⌨️  Press ENTER once connected to start download...")
            except EOFError:
                logger.warning("[WIFI] No stdin; continuing without manual confirmation.")
        await asyncio.get_event_loop().run_in_executor(None, wait_input)

    receiver = MTAReceiver(
        output_dir=output_dir,
        on_request=on_request,
        on_text=on_text,
    )

    try:
        files = await receiver.listen(
            device_name=device_name,
            ble_provider=ble,
            on_p2p=on_p2p,
            timeout=timeout,
        )
    except Exception as e:
        logger.error("[RECV] ❌ Transfer failed: %s", e)
        files = []

    if files:
        logger.info("[RECV] ✅ Success! %s file(s) received.", len(files))
        for f in files:
            logger.info("[FILE] 💾 %s (%s bytes) -> %s", f.name, f.size, f.path)
    else:
        logger.info("[RECV] ⏹️  Session ended.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="mtapy Linux Demo (BlueZ + nmcli)")
    parser.add_argument("--name", type=str, default="Ubuntu-PC", help="Name to display when receiving")
    parser.add_argument("--timeout", type=float, default=3600.0, help="Timeout in seconds (default 1 hour)")
    parser.add_argument("--no-auto-connect", action="store_true", help="Don't auto-connect via nmcli")
    parser.add_argument("--full-layout", action="store_true",
                        help="Use the full MTA advertisement layout (requires BlueZ >= 5.55)")
    args = parser.parse_args()

    try:
        asyncio.run(listen_for_transfers(
            device_name=args.name,
            timeout=args.timeout,
            auto_connect=not args.no_auto_connect,
            full_layout=args.full_layout,
        ))
    except KeyboardInterrupt:
        logger.warning("\n\nStopped by user.")