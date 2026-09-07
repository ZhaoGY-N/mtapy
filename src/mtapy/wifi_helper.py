import subprocess
import shutil
import time
import sys
import re
import glob
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Track the network we took over so restore_wifi() can bring it back even
# when called without arguments from a different layer (e.g. demo/worker).
_TAKEOVER_STATE = {"device": None, "connection": None}


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


def connect_to_wifi(ssid: str, password: str, bssid: Optional[str] = None,
                    freq: Optional[int] = None) -> bool:
    """
    Connect to a Wi-Fi network.

    - macOS: uses networksetup
    - Linux: uses nmcli (NetworkManager)

    Args:
        ssid: Network name (e.g. "DIRECT-XXXXXXXX")
        password: Network password
        bssid: Optional BSSID (for Android P2P groups, the phone's P2P MAC)
        freq: Optional frequency in MHz of the P2P group (used to detect a
              same-channel conflict with the current connection)

    Returns True if successful.
    """
    if sys.platform == "darwin":
        return _connect_to_wifi_macos(ssid, password)
    elif sys.platform.startswith("linux"):
        return _connect_to_wifi_linux(ssid, password, bssid, freq)
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


def _sudo_available() -> bool:
    """Check if passwordless sudo is configured for the WiFi tools.

    The sudoers allow-list only covers specific commands (not `true`), so
    probe one of those instead of a generic sudo test.
    """
    try:
        result = subprocess.run(
            ["sudo", "-n", "/usr/sbin/wpa_supplicant", "-h"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        # -h prints usage to stdout and exits 0 (or 1); the key is that it
        # ran without asking for a password.
        return result.returncode in (0, 1)
    except Exception:
        return False


def _wpa_terminate(device: str) -> None:
    """Gracefully stop our wpa_supplicant on ``device`` (no pkill).

    Uses the dedicated mtapy control directory so we only ever stop the
    instance we started (NetworkManager's dbus-global instance uses a
    different socket and is left untouched).
    """
    subprocess.run(
        ["sudo", "wpa_cli", "-p", "/run/mtapy_wpa", "-i", device, "terminate"],
        capture_output=True, text=True, timeout=15,
    )
    time.sleep(1)


def _wpa_cli(device: str, *args: str) -> str:
    """Run wpa_cli against our dedicated ctrl dir and return stdout."""
    result = subprocess.run(
        ["sudo", "wpa_cli", "-p", "/run/mtapy_wpa", "-i", device, *args],
        capture_output=True, text=True, timeout=10,
    )
    return result.stdout


def _connect_wifi_wpasupplicant(ssid: str, password: str,
                                bssid: Optional[str], device: str,
                                freq: Optional[int] = None) -> bool:
    """Connect using wpa_supplicant directly (fast, bypasses NM's scan).

    Key insight (verified on this machine): if the adapter is still
    associated with its current AP, wpa_supplicant gets stuck in SCANNING
    and never associates.  So we FIRST disconnect (while NM still manages
    the device), then hand it to our own wpa_supplicant with the phone's
    network preloaded — it associates in ~2s.

    Requires passwordless sudo for wpa_supplicant/wpa_cli/dhclient
    (see scripts/setup_mtapy_sudoers.sh).
    """
    # Preload the DIRECT network into the config.
    config = f'ctrl_interface=/run/mtapy_wpa\nupdate_config=1\n\n' \
             f'network={{\n    ssid="{ssid}"\n    psk="{password}"\n' \
             f'    key_mgmt=WPA-PSK\n    scan_ssid=1\n'
    if bssid:
        config += f'    bssid={bssid}\n'
    config += '}\n'
    Path("/tmp/mtapy_wpa.conf").write_text(config)

    # Disassociate while NM still manages the device, then stop NM
    # management.  `managed no` alone leaves the adapter associated with the
    # old AP, which keeps wpa_supplicant stuck in SCANNING.
    subprocess.run(
        ["nmcli", "device", "disconnect", device],
        capture_output=True, text=True, timeout=15,
    )
    time.sleep(1)
    subprocess.run(
        ["nmcli", "device", "set", device, "managed", "no"],
        capture_output=True, text=True, timeout=15,
    )
    time.sleep(1)

    # Stop any leftover instance of ours on the device.
    _wpa_terminate(device)
    # Ensure our dedicated ctrl directory exists.
    subprocess.run(
        ["sudo", "mkdir", "-p", "/run/mtapy_wpa"],
        capture_output=True, text=True, timeout=15,
    )

    # Start wpa_supplicant bound to the mtapy control directory.
    proc = subprocess.run(
        ["sudo", "wpa_supplicant", "-B", "-i", device,
         "-c", "/tmp/mtapy_wpa.conf", "-C", "/run/mtapy_wpa"],
        capture_output=True, text=True, timeout=15,
    )
    if proc.returncode != 0:
        logger.error("[WIFI] wpa_supplicant start failed: %s", proc.stderr.strip())
        return False

    # Wait for the WPA handshake to complete.
    for attempt in range(30):
        stdout = _wpa_cli(device, "status")
        if "wpa_state=COMPLETED" in stdout:
            break
        if attempt % 5 == 0:
            state_line = next(
                (l for l in stdout.splitlines() if "wpa_state" in l or "ssid" in l),
                "(no state)",
            )
            logger.info("[WIFI] wpa_supplicant attempt %d: %s", attempt, state_line.strip())
        time.sleep(0.5)
    else:
        logger.error("[WIFI] wpa_supplicant did not reach COMPLETED")
        final = _wpa_cli(device, "status")
        logger.error("[WIFI] final wpa_cli status:\n%s", final)
        scan = _wpa_cli(device, "scan_results")
        logger.error("[WIFI] scan_results:\n%s", scan)
        # Hand the device back to NetworkManager so the nmcli fallback works.
        _wpa_terminate(device)
        subprocess.run(
            ["nmcli", "device", "set", device, "managed", "yes"],
            capture_output=True, text=True, timeout=15,
        )
        time.sleep(1)
        return False

    # Obtain an IP from the phone's P2P group owner.
    subprocess.run(
        ["sudo", "dhclient", device],
        capture_output=True, text=True, timeout=20,
    )

    # Disable Wi-Fi power save.  wpa_supplicant leaves it ON by default, and
    # on MediaTek (MT7921) that makes the radio sleep periodically — which
    # stalls/kills long transfers (~mid-way) that phone-to-phone links handle
    # fine.  NetworkManager normally turns power save off; we must too.
    # `wpa_cli SET power_save 0` goes through the already-authorized wpa_cli.
    _wpa_cli(device, "SET", "power_save", "0")
    logger.info("[WIFI] Power save disabled on %s", device)

    logger.info("[WIFI] ✅ Connected to '%s' via wpa_supplicant", ssid)
    return True


def _find_wifi_device() -> Optional[str]:
    """Return any Wi-Fi device, regardless of connection/managed state."""
    try:
        result = subprocess.run(
            ["nmcli", "-t", "-f", "DEVICE,TYPE", "device", "status"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        for line in result.stdout.splitlines():
            parts = line.split(":")
            if len(parts) >= 2 and parts[1] == "wifi":
                return parts[0]
    except Exception:
        pass
    return None


def restore_wifi(device: Optional[str] = None,
                 prev_conn: Optional[str] = None) -> None:
    """Restore NetworkManager management after a wpa_supplicant session.

    Uses the takeover state recorded when wpa_supplicant took over the
    device, so it works even when called without arguments from another
    layer.
    """
    global _TAKEOVER_STATE
    device = device or _TAKEOVER_STATE["device"] or _find_wifi_device()
    prev_conn = prev_conn or _TAKEOVER_STATE["connection"]
    _TAKEOVER_STATE.update(device=None, connection=None)
    if not device:
        return
    _wpa_terminate(device)
    subprocess.run(
        ["sudo", "dhclient", "-r", device],
        capture_output=True, text=True, timeout=15,
    )
    subprocess.run(
        ["nmcli", "device", "set", device, "managed", "yes"],
        capture_output=True, text=True, timeout=15,
    )
    time.sleep(2)
    # The previous connection's network may be stale in NM's scan cache after
    # the wpa_supplicant session; rescan so a reconnect can find it.
    subprocess.run(
        ["nmcli", "device", "wifi", "rescan"],
        capture_output=True, text=True, timeout=15,
    )
    if prev_conn:
        # Retry the reconnect briefly (NM can miss it right after a rescan).
        for _ in range(4):
            time.sleep(2)
            result = subprocess.run(
                ["nmcli", "connection", "up", prev_conn],
                capture_output=True, text=True, timeout=20,
            )
            if result.returncode == 0:
                break
            logger.warning("[WIFI] restore attempt failed: %s",
                           (result.stderr or result.stdout).strip())


def _current_freq(device: str) -> Optional[int]:
    """Return the frequency (MHz) the Wi-Fi device is currently on."""
    try:
        result = subprocess.run(
            ["iw", "dev", device, "info"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        for line in result.stdout.splitlines():
            if "MHz" in line and "channel" in line:
                m = re.search(r"\((\d+) MHz\)", line)
                if m:
                    return int(m.group(1))
    except Exception:
        pass
    return None


def _connect_to_wifi_linux(ssid: str, password: str, bssid: Optional[str] = None,
                           freq: Optional[int] = None) -> bool:
    """Connect to a Wi-Fi network using nmcli (NetworkManager) on Linux.

    The phone's P2P group (DIRECT-XXX) is freshly created when it writes the
    P2P info over BLE, and NetworkManager's scan cache usually misses it —
    but a raw ``iw scan`` sees it, so the network *is* there and responds to
    probes.  The BSSID-pinned profile connect does a fresh directed probe
    each time, so we retry it quickly back-to-back to catch a responsive
    window.

    If the phone's group is on the same channel as our current connection,
    the adapter cannot join it while associated, so we disconnect first.
    """
    if shutil.which("nmcli") is None:
        logger.error("[WIFI] ❌ nmcli not found (is NetworkManager installed?)")
        return False

    device = _get_wifi_device()
    prev_conn = _get_current_connection(device) if device else None
    logger.info("[WIFI] 🔄 Connecting to '%s' (device=%s)...", ssid, device)

    # Fast path: wpa_supplicant directly (needs passwordless sudo).
    if device and _sudo_available():
        logger.info("[WIFI] Trying wpa_supplicant (fast path)...")
        # Remember what we're taking over so restore_wifi() can bring it back.
        global _TAKEOVER_STATE
        _TAKEOVER_STATE.update(device=device, connection=prev_conn)
        if _connect_wifi_wpasupplicant(ssid, password, bssid, device, freq):
            return True
        logger.warning("[WIFI] wpa_supplicant failed; falling back to nmcli")

    logger.info("[WIFI] Connecting via nmcli...")

    deadline = time.time() + 30
    disconnected = False

    # Same-channel conflict: if the phone's group shares the channel of our
    # current connection, drop the current connection first so the adapter
    # can freely probe/join the phone's group.
    if freq and device:
        cur = _current_freq(device)
        if cur is not None and abs(cur - freq) < 20:
            logger.warning(
                "[WIFI] P2P 组与当前连接同频道 (%d MHz)，先断开 %s",
                freq, device,
            )
            subprocess.run(
                ["nmcli", "device", "disconnect", device],
                capture_output=True,
                text=True,
                timeout=15,
            )
            disconnected = True

    while time.time() < deadline:
        # BSSID-profile connect: a fresh directed probe each attempt.
        if _nmcli_profile_connect(ssid, password, bssid, timeout=10):
            return True

        # Maybe it also showed up in NetworkManager's scan cache now.
        if ssid in _nmcli_wifi_list_ssids():
            if _nmcli_connect(ssid, password, bssid=bssid):
                return True

        # Late fallback: disconnect so the adapter does a full-band scan
        # (only in the last stretch, to avoid dropping the user's Wi-Fi
        # needlessly).
        if not disconnected and device and time.time() > deadline - 12:
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
                           bssid: Optional[str] = None,
                           timeout: int = 15) -> bool:
    """Connect via a pinned connection profile (BSSID + hidden).

    A plain ``nmcli device wifi connect`` relies on NetworkManager's scan
    cache, which often misses the phone's freshly-created P2P GO network.
    Activating a profile with an explicit BSSID and ``hidden yes`` makes
    NetworkManager probe the BSSID directly.  ``timeout`` bounds how long
    we wait for the activation (short, so failures are detected fast and
    the profile can be retried quickly).
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

    try:
        up = subprocess.run(
            ["nmcli", "connection", "up", con_name],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        logger.warning("[WIFI] profile connect timed out after %ss", timeout)
        subprocess.run(
            ["nmcli", "connection", "delete", con_name],
            capture_output=True,
            text=True,
            timeout=15,
        )
        return False

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