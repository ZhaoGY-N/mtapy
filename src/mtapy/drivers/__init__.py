"""
Platform-specific BLE drivers.

This module provides platform-specific implementations of the BLEProvider interface.

Available drivers:
- bleak: Cross-platform BLE client using bleak (Windows/macOS/Linux)
- macos: macOS native using CoreBluetooth (GATT server support)
- linux: Linux native using BlueZ D-Bus (GATT server support)

Usage:
    from mtapy.drivers import get_ble_provider
    ble = get_ble_provider()  # Auto-selects based on platform
"""

from ..interfaces import BLEProvider


def get_ble_provider() -> BLEProvider:
    """
    Get the best BLE provider for the current platform.

    - macOS with pyobjc: CoreBluetoothBLEProvider (GATT server support)
    - Linux with dbus-fast: BlueZBLEProvider (GATT server support)
    - Otherwise: BleakBLEProvider (client-only)
    """
    import sys

    if sys.platform == "darwin":
        try:
            return get_macos_ble_provider()
        except ImportError:
            pass  # pyobjc not installed

    if sys.platform.startswith("linux"):
        try:
            return get_linux_ble_provider()
        except ImportError:
            pass  # dbus-fast not installed

    return get_bleak_ble_provider()


def get_bleak_ble_provider() -> BLEProvider:
    """Get the Bleak-based BLE provider (client-only)."""
    from .bleak_driver import BleakBLEProvider
    return BleakBLEProvider()


def get_macos_ble_provider() -> BLEProvider:
    """Get the macOS-specific BLE provider (GATT server support)."""
    from .macos import CoreBluetoothBLEProvider
    return CoreBluetoothBLEProvider()


def get_linux_ble_provider() -> BLEProvider:
    """Get the Linux-specific BLE provider (GATT server support)."""
    from .linux import BlueZBLEProvider
    return BlueZBLEProvider()


__all__ = [
    "get_ble_provider",
    "get_bleak_ble_provider",
    "get_macos_ble_provider",
    "get_linux_ble_provider",
    "BLEProvider",
]
