"""
Linux BLE implementation using BlueZ D-Bus API via dbus-fast.

Provides GATT server (BLE peripheral) and LE advertising support for Linux,
enabling the machine to appear in the Android 互传 (MTA) device list and
receive files from Xiaomi/OPPO/vivo phones.

Requires:
    pip install dbus-fast

Notes on advertising size:
    BlueZ < 5.55 only supports legacy advertising (31-byte adv data), and
    everything except the local name must fit in that single packet.  The
    full MTA advertisement (128-bit service UUID + 6-byte and 27-byte
    service data segments) needs 62 bytes, so on BlueZ 5.53 we advertise a
    reduced layout: the 128-bit discovery UUID + the 6-byte service data
    segment in the adv packet, and the device name in the scan response.
    Upgrading to BlueZ >= 5.55 (extended advertising) allows the full
    layout; set ``full_layout=True`` on the provider to enable it.
"""

import logging
import os
from typing import Callable, Awaitable, Optional, Dict, Tuple, List

logger = logging.getLogger(__name__)

from dbus_fast import BusType, Variant
from dbus_fast.aio import MessageBus
from dbus_fast.service import ServiceInterface, method, dbus_property

from ..interfaces import BLEProvider, BLEConnection, DiscoveredDevice

BLUEZ_SERVICE = "org.bluez"
ADAPTER_IFACE = "org.bluez.Adapter1"
LE_ADV_MGR_IFACE = "org.bluez.LEAdvertisingManager1"
GATT_MGR_IFACE = "org.bluez.GattManager1"

# D-Bus object paths for our GATT application and advertisement
APP_PATH = "/com/mtapy/app"
SVC_PATH = "/com/mtapy/app/service0"
CHAR_PREFIX = "/com/mtapy/app/service0/char"
ADV_PATH = "/com/mtapy/advertisement"

# MTA service data segment UUIDs (16-bit Bluetooth base UUIDs)
SVC_DATA_1_UUID = "000001ff-0000-1000-8000-00805f9b34fb"
SVC_DATA_2_UUID = "0000ffff-0000-1000-8000-00805f9b34fb"


class MtaCharacteristic(ServiceInterface):
    """A GATT characteristic exported to BlueZ (org.bluez.GattCharacteristic1)."""

    def __init__(
        self,
        path: str,
        service_path: str,
        uuid: str,
        flags: List[str],
        on_read: Callable[[str], Awaitable[bytes]],
        on_write: Callable[[str, bytes], Awaitable[None]],
    ):
        super().__init__("org.bluez.GattCharacteristic1")
        self._path = path
        self._service_path = service_path
        self._uuid = uuid
        self._flags = flags
        self._on_read = on_read
        self._on_write = on_write
        self._write_buffer = b""

    @dbus_property()
    def UUID(self) -> "s":
        return self._uuid

    @UUID.setter
    def UUID(self, val):
        self._uuid = val

    @dbus_property()
    def Service(self) -> "o":
        return self._service_path

    @Service.setter
    def Service(self, val):
        self._service_path = val

    @dbus_property()
    def Flags(self) -> "as":
        return self._flags

    @Flags.setter
    def Flags(self, val):
        self._flags = val

    @method()
    async def ReadValue(self, options: "a{sv}") -> "ay":
        """Handle a read request from a BLE central (the phone).

        BlueZ passes an ``offset`` in the options dict for Read Blob
        requests (values longer than the negotiated MTU); we must return
        the data starting at that offset.
        """
        try:
            data = await self._on_read(self._uuid)
            offset = 0
            if options and "offset" in options:
                offset = options["offset"].value
            logger.info(
                "[GATT] ReadValue %s offset=%d -> %d bytes",
                self._uuid, offset, len(data),
            )
            # Return bytes (not a list of ints) — dbus-fast's "ay" serializer
            # fails with "can't concat list to bytearray" on a plain list.
            return bytes(data[offset:])
        except Exception:
            logger.exception("GATT ReadValue failed for %s", self._uuid)
            raise

    @method()
    async def WriteValue(self, value: "ay", options: "a{sv}"):
        """Handle a write request from a BLE central (the phone)."""
        data = bytes(value)
        offset = 0
        if options and "offset" in options:
            offset = options["offset"].value
        logger.info(
            "[GATT] WriteValue %s offset=%d len=%d data=%s",
            self._uuid, offset, len(data), data[:80],
        )
        if offset > 0:
            # Long write continuation: accumulate with the previous buffer.
            self._write_buffer = self._write_buffer[:offset] + data
            return
        self._write_buffer = data
        try:
            await self._on_write(self._uuid, data)
        except Exception:
            logger.exception("GATT WriteValue failed for %s", self._uuid)
            raise


class MtaService(ServiceInterface):
    """A GATT service exported to BlueZ (org.bluez.GattService1)."""

    def __init__(self, path: str, uuid: str, characteristics: List[MtaCharacteristic]):
        super().__init__("org.bluez.GattService1")
        self._path = path
        self._uuid = uuid
        self._characteristics = characteristics

    @dbus_property()
    def UUID(self) -> "s":
        return self._uuid

    @UUID.setter
    def UUID(self, val):
        self._uuid = val

    @dbus_property()
    def Primary(self) -> "b":
        return True

    @Primary.setter
    def Primary(self, val):
        pass

    @dbus_property()
    def Characteristics(self) -> "ao":
        return [c._path for c in self._characteristics]

    @Characteristics.setter
    def Characteristics(self, val):
        pass


class MtaAdvertisement(ServiceInterface):
    """An LE advertisement exported to BlueZ (org.bluez.LEAdvertisement1)."""

    def __init__(
        self,
        path: str,
        name: str,
        service_uuids: List[str],
        service_data: Dict[str, bytes],
    ):
        super().__init__("org.bluez.LEAdvertisement1")
        self._path = path
        self._name = name
        self._service_uuids = service_uuids
        self._service_data = service_data

    @dbus_property()
    def Type(self) -> "s":
        return "peripheral"

    @Type.setter
    def Type(self, val):
        pass

    @dbus_property()
    def ServiceUUIDs(self) -> "as":
        return self._service_uuids

    @ServiceUUIDs.setter
    def ServiceUUIDs(self, val):
        self._service_uuids = val

    @dbus_property()
    def ServiceData(self) -> "a{sv}":
        return {k: Variant("ay", v) for k, v in self._service_data.items()}

    @ServiceData.setter
    def ServiceData(self, val):
        self._service_data = {k: v.value for k, v in val.items()}

    @dbus_property()
    def LocalName(self) -> "s":
        return self._name

    @LocalName.setter
    def LocalName(self, val):
        self._name = val


class BlueZBLEProvider(BLEProvider):
    """
    Linux BLE provider using the BlueZ D-Bus API via dbus-fast.

    Implements the BLE peripheral side (GATT server + advertising) that
    mtapy's receiver needs.  Scanning and client connections delegate to
    bleak, which already works on Linux.
    """

    def __init__(self, adapter_path: Optional[str] = None, full_layout: bool = False):
        self._adapter_path = adapter_path
        # If True, advertise the full MTA layout (needs BlueZ >= 5.55).
        self._full_layout = full_layout

        self._bus: Optional[MessageBus] = None
        self._exported: List[Tuple[str, ServiceInterface]] = []
        self._adv: Optional[MtaAdvertisement] = None
        self._adv_registered = False
        self._app_registered = False
        self._bleak = None

    # ------------------------------------------------------------------
    # D-Bus helpers
    # ------------------------------------------------------------------

    async def _get_bus(self) -> MessageBus:
        if self._bus is None:
            self._bus = await MessageBus(bus_type=BusType.SYSTEM).connect()
        return self._bus

    async def _resolve_adapter_path(self) -> str:
        if self._adapter_path:
            return self._adapter_path

        bus = await self._get_bus()

        # Fast path: hci0
        try:
            introspection = await bus.introspect(BLUEZ_SERVICE, "/org/bluez/hci0")
            obj = bus.get_proxy_object(BLUEZ_SERVICE, "/org/bluez/hci0", introspection)
            adapter = obj.get_interface(ADAPTER_IFACE)
            if await adapter.get_powered():
                self._adapter_path = "/org/bluez/hci0"
                return self._adapter_path
        except Exception:
            pass

        # Fallback: discover the first powered adapter via ObjectManager
        introspection = await bus.introspect(BLUEZ_SERVICE, "/")
        om = bus.get_proxy_object(BLUEZ_SERVICE, "/", introspection)
        om_iface = om.get_interface("org.freedesktop.DBus.ObjectManager")
        objs = await om_iface.call_get_managed_objects()
        for path, ifaces in objs.items():
            if ADAPTER_IFACE in ifaces:
                powered = ifaces[ADAPTER_IFACE].get("Powered")
                if powered is None or powered.value:
                    self._adapter_path = path
                    return path

        raise RuntimeError("No powered Bluetooth adapter found")

    async def _get_interface(self, iface_name: str):
        bus = await self._get_bus()
        adapter_path = await self._resolve_adapter_path()
        introspection = await bus.introspect(BLUEZ_SERVICE, adapter_path)
        obj = bus.get_proxy_object(BLUEZ_SERVICE, adapter_path, introspection)
        return obj.get_interface(iface_name)

    # ------------------------------------------------------------------
    # GATT server (peripheral)
    # ------------------------------------------------------------------

    async def setup_gatt_server(
        self,
        service_uuid: str,
        characteristics: Dict[str, Tuple[bool, bool]],
        on_read: Callable[[str], Awaitable[bytes]],
        on_write: Callable[[str, bytes], Awaitable[None]],
    ) -> None:
        """Setup the MTA GATT server via BlueZ GattManager1."""
        bus = await self._get_bus()

        # Build characteristic objects
        chars: List[MtaCharacteristic] = []
        for i, (char_uuid, (readable, writable)) in enumerate(characteristics.items()):
            flags = []
            if readable:
                flags.append("read")
            if writable:
                flags.append("write")
                flags.append("write-without-response")
            char = MtaCharacteristic(
                f"{CHAR_PREFIX}{i}",
                SVC_PATH,
                char_uuid,
                flags,
                on_read,
                on_write,
            )
            bus.export(char._path, char)
            self._exported.append((char._path, char))
            chars.append(char)

        # Build service object
        svc = MtaService(SVC_PATH, service_uuid, chars)
        bus.export(SVC_PATH, svc)
        self._exported.append((SVC_PATH, svc))

        # Register the application with BlueZ
        gatt_mgr = await self._get_interface(GATT_MGR_IFACE)
        await gatt_mgr.call_register_application(APP_PATH, {})
        self._app_registered = True
        logger.info(
            "GATT server registered: service=%s on %s", service_uuid, self._adapter_path
        )

    async def stop_gatt_server(self) -> None:
        """Stop the GATT server."""
        bus = await self._get_bus()
        if self._app_registered:
            try:
                gatt_mgr = await self._get_interface(GATT_MGR_IFACE)
                await gatt_mgr.call_unregister_application(APP_PATH)
            except Exception:
                logger.debug("Failed to unregister GATT application", exc_info=True)
            self._app_registered = False

        for path, interface in self._exported:
            try:
                bus.unexport(path, interface)
            except Exception:
                pass
        self._exported.clear()

    # ------------------------------------------------------------------
    # Advertising (peripheral)
    # ------------------------------------------------------------------

    async def start_advertising(
        self,
        name: str,
        service_uuid: str,
        service_data: Optional[Dict[str, bytes]] = None,
    ) -> None:
        """Start advertising as an MTA device via BlueZ LEAdvertisingManager1."""
        bus = await self._get_bus()

        if self._full_layout:
            # Full MTA layout: both service data segments (needs BlueZ >= 5.55)
            svc_data = {
                SVC_DATA_1_UUID: os.urandom(2) + b"\x00" * 4,
                SVC_DATA_2_UUID: self._build_name_service_data(name),
            }
        else:
            # Reduced layout for BlueZ < 5.55 (31-byte legacy advertising):
            # the 128-bit discovery UUID plus the 6-byte service data segment
            # fit exactly in the adv packet; the name goes in the scan response.
            svc_data = {
                SVC_DATA_1_UUID: os.urandom(2) + b"\x00" * 4,
            }

        if service_data:
            svc_data.update(service_data)

        adv = MtaAdvertisement(ADV_PATH, name, [str(service_uuid)], svc_data)
        bus.export(ADV_PATH, adv)
        self._exported.append((ADV_PATH, adv))
        self._adv = adv

        adv_mgr = await self._get_interface(LE_ADV_MGR_IFACE)
        await adv_mgr.call_register_advertisement(ADV_PATH, {})
        self._adv_registered = True
        logger.info(
            "Advertising as '%s' (service %s, %d service-data segment(s))",
            name,
            service_uuid,
            len(svc_data),
        )

    async def stop_advertising(self) -> None:
        """Stop BLE advertising."""
        bus = await self._get_bus()
        if self._adv_registered:
            try:
                adv_mgr = await self._get_interface(LE_ADV_MGR_IFACE)
                await adv_mgr.call_unregister_advertisement(ADV_PATH)
            except Exception:
                logger.debug("Failed to unregister advertisement", exc_info=True)
            self._adv_registered = False

        if self._adv is not None:
            try:
                bus.unexport(ADV_PATH, self._adv)
            except Exception:
                pass
            self._adv = None

    @staticmethod
    def _build_name_service_data(name: str) -> bytes:
        """Build the 27-byte MTA service data segment containing the name."""
        name_bytes = name.encode("utf-8")[:16].ljust(16, b"\x00")
        # 8 zero bytes + 2 random bytes + 16 name bytes + 1 flag (5GHz)
        return b"\x00" * 8 + os.urandom(2) + name_bytes + b"\x01"

    # ------------------------------------------------------------------
    # Scanning / client connections (delegated to bleak)
    # ------------------------------------------------------------------

    def _get_bleak(self):
        if self._bleak is None:
            from .bleak_driver import BleakBLEProvider

            self._bleak = BleakBLEProvider()
        return self._bleak

    async def start_scan(
        self,
        on_device_found: Callable[[DiscoveredDevice], Awaitable[None]],
        timeout: float = 30.0,
    ) -> None:
        await self._get_bleak().start_scan(on_device_found, timeout)

    async def stop_scan(self) -> None:
        await self._get_bleak().stop_scan()

    async def connect(self, address: str) -> BLEConnection:
        return await self._get_bleak().connect(address)


def get_linux_ble_provider() -> BLEProvider:
    """Get the Linux BLE provider with GATT server support."""
    return BlueZBLEProvider()