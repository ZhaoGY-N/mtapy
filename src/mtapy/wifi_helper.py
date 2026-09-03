import subprocess
import shutil
import time
import sys
import re
import glob
import logging
from typing import Optional

logger = logging.getLogger(__name__)


def get_wifi_interface() -> str:
    """
    Detect the Wi-Fi interface (e.g. en0) on macOS using networksetup.
    """
    if sys.platform != "darwin":
        return "wlan0"  # Fallback guess for Linux

    try:
        # List all hardware ports
        output = subprocess.check_output(
            ["networksetup", "-listallhardwareports"],
            encoding="utf-8"
        )

        # Parse output to find "Wi-Fi" or "Airport"
        # Format is:
        # Hardware Port: Wi-Fi
        # Device: en0
        lines = output.splitlines()
        for i, line in enumerate(lines):
            if "Hardware Port: Wi-Fi" in line or "Hardware Port: AirPort" in line:
                # The next line should be "Device: enX"
                if i + 1 < len(lines):
                    device_line = lines[i + 1]
                    match = re.search(r"Device: (en\d+)", device_line)
                    if match:
                        return match.group(1)

    except Exception as e:
        logger.warning("[WIFI] ⚠️  Could not detect Wi-Fi interface: %s", e)

    return "en0"  # Default fallback


def get_wifi_mac() -> str:
    """
    Get the Wi-Fi interface MAC address for the current platform.

    Used for the DeviceInfo.mac field that the phone reads over BLE.
    """
    if sys.platform.startswith("linux"):
        # Look for a wireless interface (wlp*, wlan*, etc.)
        for iface in sorted(glob.glob("/sys/class/net/wl*")):
            try:
                with open(f"{iface}/address") as f:
                    mac = f.read().strip()
                if mac and mac != "00:00:00:00:00:00":
                    return mac
            except OSError:
                continue
        logger.warning("[WIFI] ⚠️  No wireless interface found for MAC lookup")
        return "00:00:00:00:00:00"

    if sys.platform == "darwin":
        interface = get_wifi_interface()
        try:
            result = subprocess.run(
                ["ifconfig", interface],
                capture_output=True,
                text=True,
            )
            for line in result.stdout.split("\n"):
                if "ether" in line:
                    return line.split()[1]
        except Exception as e:
            logger.warning("[WIFI] ⚠️  Could not read MAC from %s: %s", interface, e)
        return "00:00:00:00:00:00"

    return "00:00:00:00:00:00"


def connect_to_wifi(ssid: str, password: str, bssid: Optional[str] = None) -> bool:
    """
    Connect to a Wi-Fi network.

    - macOS: uses networksetup
    - Linux: uses nmcli (NetworkManager)

    Args:
        ssid: Network name (e.g. "DIRECT-XXXXXXXX")
        password: Network password
        bssid: Optional BSSID (for Android P2P groups, the phone's P2P MAC)

    Returns True if successful.
    """
    if sys.platform == "darwin":
        return _connect_to_wifi_macos(ssid, password)
    elif sys.platform.startswith("linux"):
        return _connect_to_wifi_linux(ssid, password, bssid)
    else:
        logger.error("[WIFI] ❌ Auto-connect not supported on this platform")
        return False


def _connect_to_wifi_macos(ssid: str, password: str) -> bool:
    """Connect to a Wi-Fi network using networksetup on macOS."""
    interface = get_wifi_interface()
    logger.info("[WIFI] 🔄 Connecting to '%s' on %s...", ssid, interface)

    try:
        # networksetup -setairportnetwork <device> <network> <password>
        # Note: networksetup can print "Could not find network" to stderr but return 0
        result = subprocess.run(
            ["networksetup", "-setairportnetwork", interface, ssid, password],
            capture_output=True,
            text=True
        )

        output = result.stdout + result.stderr

        # Check for known failure strings
        if "Could not find network" in output or "Error" in output:
            logger.error("[WIFI] ❌ %s", output.strip())
            return False

        if result.returncode != 0:
            logger.error("[WIFI] ❌ Command failed: %s", output.strip())
            return False

        logger.info("[WIFI] ✅ Connected to '%s'", ssid)
        # Give it a moment to acquire IP
        time.sleep(2.0)
        return True
    except Exception as e:
        logger.error("[WIFI] ❌ Failed to connect: %s", e)
        return False


def _nmcli_wifi_list_ssids() -> list:
    """Return the list of SSIDs currently in NetworkManager's scan cache."""
    try:
        result = subprocess.run(
            ["nmcli", "-t", "-f", "SSID", "device", "wifi", "list"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        ssids = [line.strip() for line in result.stdout.splitlines() if line.strip()]
        return ssids
    except Exception:
        return []


def _get_wifi_device() -> Optional[str]:
    """Return the first managed Wi-Fi device name (e.g. wlp9s0)."""
    try:
        result = subprocess.run(
            ["nmcli", "-t", "-f", "DEVICE,TYPE,STATE", "device", "status"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        for line in result.stdout.splitlines():
            parts = line.split(":")
            if len(parts) >= 3 and parts[1] == "wifi" and parts[2] == "connected":
                return parts[0]
    except Exception:
        pass
    return None


def _get_current_connection(device: str) -> Optional[str]:
    """Return the name of the connection currently active on ``device``."""
    try:
        result = subprocess.run(
            ["nmcli", "-t", "-f", "DEVICE,CONNECTION", "device", "status"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        for line in result.stdout.splitlines():
            parts = line.split(":")
            if len(parts) >= 2 and parts[0] == device:
                return parts[1] or None
    except Exception:
        pass
    return None


def _connect_to_wifi_linux(ssid: str, password: str, bssid: Optional[str] = None) -> bool:
    """Connect to a Wi-Fi network using nmcli (NetworkManager) on Linux.

    The phone's P2P group (DIRECT-XXX) is freshly created when it writes the
    P2P info over BLE, so it may not yet be in NetworkManager's scan cache.
    NetworkManager rate-limits scans (~10s interval) and rejects scans that
    follow too quickly, so we must pace ourselves: one rescan, an 8-second
    wait for it to complete, then poll.  As a fallback we temporarily
    disconnect the Wi-Fi device so the adapter does a full-band scan.
    """
    if shutil.which("nmcli") is None:
        logger.error("[WIFI] ❌ nmcli not found (is NetworkManager installed?)")
        return False

    device = _get_wifi_device()
    prev_conn = _get_current_connection(device) if device else None
    logger.info("[WIFI] 🔄 Connecting to '%s' via nmcli (device=%s)...", ssid, device)

    deadline = time.time() + 30
    disconnected = False

    # The BSSID-profile connect is the one that reliably works, but it must
    # run while the phone's group is still fresh.  Try it first.
    if _nmcli_profile_connect(ssid, password, bssid):
        return True

    while time.time() < deadline:
        # One rescan, then give it time to complete before polling.
        try:
            subprocess.run(
                ["nmcli", "device", "wifi", "rescan"],
                capture_output=True,
                text=True,
                timeout=15,
            )
        except Exception:
            pass  # rescan can fail if a scan is already running; ignore
        time.sleep(8)

        if ssid in _nmcli_wifi_list_ssids():
            if _nmcli_connect(ssid, password, bssid=bssid):
                return True

        # The BSSID-profile connect again (the group may have become
        # probe-able by now).
        if _nmcli_profile_connect(ssid, password, bssid):
            return True

        # If we're still associated, disconnect so the adapter does a full
        # scan that can see the freshly-created P2P GO network.
        if not disconnected and device:
            logger.warning("[WIFI] Not visible yet; temporarily disconnecting %s", device)
            subprocess.run(
                ["nmcli", "device", "disconnect", device],
                capture_output=True,
                text=True,
                timeout=15,
            )
            disconnected = True

        time.sleep(2)

    # Last-resort directed connect (bypasses the scan list).
    if _nmcli_connect(ssid, password, hidden=True, bssid=bssid):
        return True

    # Restore the previous connection so the user isn't left offline.
    if disconnected and prev_conn:
        logger.warning("[WIFI] Restoring previous connection '%s'", prev_conn)
        subprocess.run(
            ["nmcli", "connection", "up", prev_conn],
            capture_output=True,
            text=True,
            timeout=30,
        )

    logger.error("[WIFI] ❌ Could not see or connect to '%s' within 30s", ssid)
    return False


def _nmcli_profile_connect(ssid: str, password: str,
                           bssid: Optional[str] = None) -> bool:
    """Connect via a pinned connection profile (BSSID + hidden).

    A plain ``nmcli device wifi connect`` relies on NetworkManager's scan
    cache, which often misses the phone's freshly-created P2P GO network.
    Activating a profile with an explicit BSSID and ``hidden yes`` makes
    NetworkManager probe the BSSID directly.
    """
    con_name = "mta-direct"
    # Remove any stale profile first.
    subprocess.run(
        ["nmcli", "connection", "delete", con_name],
        capture_output=True,
        text=True,
        timeout=15,
    )

    args = [
        "nmcli", "connection", "add", "type", "wifi", "con-name", con_name,
        "ssid", ssid,
        "wifi-sec.key-mgmt", "wpa-psk",
        "wifi-sec.psk", password,
        "wifi.hidden", "yes",
    ]
    if bssid:
        args += ["wifi.bssid", bssid]

    add = subprocess.run(args, capture_output=True, text=True, timeout=15)
    if add.returncode != 0:
        logger.warning("[WIFI] profile add failed: %s", add.stderr.strip())
        return False

    up = subprocess.run(
        ["nmcli", "connection", "up", con_name],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if up.returncode == 0:
        logger.info("[WIFI] ✅ Connected to '%s' via BSSID profile", ssid)
        time.sleep(2.0)
        return True

    logger.warning("[WIFI] profile connect failed: %s", up.stderr.strip())
    subprocess.run(
        ["nmcli", "connection", "delete", con_name],
        capture_output=True,
        text=True,
        timeout=15,
    )
    return False


def _nmcli_connect(ssid: str, password: str, hidden: bool = False,
                   bssid: Optional[str] = None) -> bool:
    """Run ``nmcli device wifi connect`` and return True on success."""
    args = ["nmcli", "device", "wifi", "connect", ssid, "password", password]
    if hidden:
        args += ["hidden", "yes"]
    if bssid:
        args += ["bssid", bssid]
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=30)
    except subprocess.TimeoutExpired:
        logger.warning("[WIFI] connect timed out")
        return False

    output = result.stdout + result.stderr
    if result.returncode == 0:
        logger.info("[WIFI] ✅ Connected to '%s'", ssid)
        # Give it a moment to acquire an IP from the P2P group owner
        time.sleep(2.0)
        return True

    logger.warning("[WIFI] connect failed: %s", output.strip())
    return False