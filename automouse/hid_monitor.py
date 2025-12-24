"""
HID device monitoring for pointing device activity detection.

Uses hidapi for raw HID access to detect mouse/trackball movement
without interfering with normal operation.
"""

import threading
import time
from typing import Callable, List, Optional, Set, Tuple
from dataclasses import dataclass

try:
    import hid
    HID_AVAILABLE = True
except ImportError:
    HID_AVAILABLE = False


# Standard HID usage pages and usages for pointing devices
USAGE_PAGE_GENERIC_DESKTOP = 0x01
USAGE_MOUSE = 0x02
USAGE_POINTER = 0x01


@dataclass
class HIDDevice:
    """Represents a HID device."""
    path: bytes
    vid: int
    pid: int
    product: str
    manufacturer: str
    serial: str
    usage_page: int
    usage: int

    @property
    def is_pointing_device(self) -> bool:
        """Check if this is a pointing device (mouse, trackball, etc)."""
        return (
            self.usage_page == USAGE_PAGE_GENERIC_DESKTOP and
            self.usage in (USAGE_MOUSE, USAGE_POINTER)
        )

    def __hash__(self):
        return hash(self.path)

    def __eq__(self, other):
        if not isinstance(other, HIDDevice):
            return False
        return self.path == other.path


def enumerate_pointing_devices() -> List[HIDDevice]:
    """
    Enumerate all connected pointing devices.
    Returns a list of HIDDevice objects for mice, trackballs, etc.
    """
    if not HID_AVAILABLE:
        return []

    devices = []
    try:
        for dev_info in hid.enumerate():
            device = HIDDevice(
                path=dev_info.get('path', b''),
                vid=dev_info.get('vendor_id', 0),
                pid=dev_info.get('product_id', 0),
                product=dev_info.get('product_string', '') or '',
                manufacturer=dev_info.get('manufacturer_string', '') or '',
                serial=dev_info.get('serial_number', '') or '',
                usage_page=dev_info.get('usage_page', 0),
                usage=dev_info.get('usage', 0)
            )
            if device.is_pointing_device:
                devices.append(device)
    except Exception:
        pass

    return devices


def enumerate_all_devices() -> List[HIDDevice]:
    """Enumerate all HID devices."""
    if not HID_AVAILABLE:
        return []

    devices = []
    try:
        for dev_info in hid.enumerate():
            devices.append(HIDDevice(
                path=dev_info.get('path', b''),
                vid=dev_info.get('vendor_id', 0),
                pid=dev_info.get('product_id', 0),
                product=dev_info.get('product_string', '') or '',
                manufacturer=dev_info.get('manufacturer_string', '') or '',
                serial=dev_info.get('serial_number', '') or '',
                usage_page=dev_info.get('usage_page', 0),
                usage=dev_info.get('usage', 0)
            ))
    except Exception:
        pass

    return devices


class HIDMonitor:
    """
    Monitors HID pointing devices for activity.

    Note: On Windows, we typically can't read raw HID from mice that are
    already claimed by the OS. For those cases, we fall back to pynput
    mouse monitoring. This class is primarily useful for:
    - Linux with proper udev rules
    - Custom HID devices that aren't claimed exclusively
    - Future Vial-QMK integration
    """

    def __init__(self, on_activity: Callable[[], None]):
        self._on_activity = on_activity
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._devices: Set[bytes] = set()
        self._target_vids_pids: Optional[Set[Tuple[int, int]]] = None

    def set_target_devices(self, vid_pid_pairs: List[Tuple[int, int]]):
        """Limit monitoring to specific VID/PID pairs."""
        self._target_vids_pids = set(vid_pid_pairs) if vid_pid_pairs else None

    def _should_monitor(self, device: HIDDevice) -> bool:
        """Check if we should monitor this device."""
        if not device.is_pointing_device:
            return False
        if self._target_vids_pids is not None:
            return (device.vid, device.pid) in self._target_vids_pids
        return True

    def start(self):
        """Start monitoring pointing devices."""
        if self._running:
            return

        self._running = True
        self._thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self._thread.start()

    def stop(self):
        """Stop monitoring."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=1.0)
            self._thread = None

    def _monitor_loop(self):
        """Main monitoring loop - polls for new devices and reads from them."""
        while self._running:
            try:
                self._update_devices()
            except Exception:
                pass
            time.sleep(1.0)  # Check for new devices every second

    def _update_devices(self):
        """Update the list of monitored devices."""
        if not HID_AVAILABLE:
            return

        current_devices = enumerate_pointing_devices()
        current_paths = {d.path for d in current_devices if self._should_monitor(d)}

        # Note: Actually reading from HID devices is complex on Windows
        # because mice are exclusively claimed by the OS input stack.
        # For the MVP, we'll rely on pynput for mouse activity detection
        # and use this for device enumeration / future Vial integration.

        self._devices = current_paths
