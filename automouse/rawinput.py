"""
Windows Raw Input API wrapper for detecting which mouse device is active.

This is the ONLY way to distinguish between multiple mice on Windows.
hidapi cannot access mice because Windows claims exclusive access.

References:
- https://asawicki.info/news_1533_handling_multiple_mice_with_raw_input
- https://learn.microsoft.com/en-us/windows/win32/inputdev/raw-input
"""

import ctypes
from ctypes import wintypes
import threading
import logging
import time
from typing import Callable, Dict, Optional

log = logging.getLogger(__name__)

# Only works on Windows
import sys
if sys.platform != 'win32':
    raise ImportError("rawinput module only works on Windows")

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

# Constants
WM_INPUT = 0x00FF
WM_DESTROY = 0x0002
RIM_TYPEMOUSE = 0
RIM_TYPEKEYBOARD = 1
RIM_TYPEHID = 2
RID_INPUT = 0x10000003
RID_HEADER = 0x10000005
RIDEV_INPUTSINK = 0x00000100
RIDI_DEVICENAME = 0x20000007
RIDI_DEVICEINFO = 0x2000000b

# Structures
class RAWINPUTDEVICE(ctypes.Structure):
    _fields_ = [
        ("usUsagePage", wintypes.USHORT),
        ("usUsage", wintypes.USHORT),
        ("dwFlags", wintypes.DWORD),
        ("hwndTarget", wintypes.HWND),
    ]

class RAWINPUTHEADER(ctypes.Structure):
    _fields_ = [
        ("dwType", wintypes.DWORD),
        ("dwSize", wintypes.DWORD),
        ("hDevice", wintypes.HANDLE),
        ("wParam", wintypes.WPARAM),
    ]

class RAWMOUSE(ctypes.Structure):
    _fields_ = [
        ("usFlags", wintypes.USHORT),
        ("usButtonFlags", wintypes.USHORT),
        ("usButtonData", wintypes.USHORT),
        ("ulRawButtons", wintypes.ULONG),
        ("lLastX", wintypes.LONG),
        ("lLastY", wintypes.LONG),
        ("ulExtraInformation", wintypes.ULONG),
    ]

class RAWINPUT(ctypes.Structure):
    class _Data(ctypes.Union):
        _fields_ = [
            ("mouse", RAWMOUSE),
        ]
    _fields_ = [
        ("header", RAWINPUTHEADER),
        ("data", _Data),
    ]

class RAWINPUTDEVICELIST(ctypes.Structure):
    _fields_ = [
        ("hDevice", wintypes.HANDLE),
        ("dwType", wintypes.DWORD),
    ]

class RID_DEVICE_INFO_MOUSE(ctypes.Structure):
    _fields_ = [
        ("dwId", wintypes.DWORD),
        ("dwNumberOfButtons", wintypes.DWORD),
        ("dwSampleRate", wintypes.DWORD),
        ("fHasHorizontalWheel", wintypes.BOOL),
    ]

class RID_DEVICE_INFO(ctypes.Structure):
    class _Data(ctypes.Union):
        _fields_ = [
            ("mouse", RID_DEVICE_INFO_MOUSE),
        ]
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("dwType", wintypes.DWORD),
        ("data", _Data),
    ]

# Window procedure type
WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_long, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)

class WNDCLASSEX(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.UINT),
        ("style", wintypes.UINT),
        ("lpfnWndProc", WNDPROC),
        ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int),
        ("hInstance", wintypes.HINSTANCE),
        ("hIcon", wintypes.HICON),
        ("hCursor", wintypes.HANDLE),
        ("hbrBackground", wintypes.HBRUSH),
        ("lpszMenuName", wintypes.LPCWSTR),
        ("lpszClassName", wintypes.LPCWSTR),
        ("hIconSm", wintypes.HICON),
    ]


class RawInputMonitor:
    """
    Monitors raw input to detect which specific mouse device is active.
    """

    def __init__(self, on_device_activity: Callable[[str], None]):
        """
        Args:
            on_device_activity: Callback with device path when activity detected
        """
        self._on_activity = on_device_activity
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._hwnd: Optional[wintypes.HWND] = None
        self._device_paths: Dict[int, str] = {}  # handle -> device path
        self._wndproc = None  # prevent garbage collection

    def start(self):
        """Start monitoring raw input in a background thread."""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        """Stop monitoring."""
        self._running = False
        if self._hwnd:
            user32.PostMessageW(self._hwnd, WM_DESTROY, 0, 0)
        if self._thread:
            self._thread.join(timeout=1.0)
            self._thread = None

    def get_device_paths(self) -> Dict[int, str]:
        """Get mapping of device handles to paths."""
        return self._device_paths.copy()

    def _enumerate_devices(self):
        """Enumerate raw input devices and get their paths."""
        num_devices = wintypes.UINT()
        user32.GetRawInputDeviceList(None, ctypes.byref(num_devices), ctypes.sizeof(RAWINPUTDEVICELIST))

        if num_devices.value == 0:
            return

        devices = (RAWINPUTDEVICELIST * num_devices.value)()
        user32.GetRawInputDeviceList(devices, ctypes.byref(num_devices), ctypes.sizeof(RAWINPUTDEVICELIST))

        for dev in devices:
            if dev.dwType == RIM_TYPEMOUSE:
                # Get device name/path
                name_size = wintypes.UINT()
                user32.GetRawInputDeviceInfoW(dev.hDevice, RIDI_DEVICENAME, None, ctypes.byref(name_size))

                if name_size.value > 0:
                    name_buffer = ctypes.create_unicode_buffer(name_size.value)
                    user32.GetRawInputDeviceInfoW(dev.hDevice, RIDI_DEVICENAME, name_buffer, ctypes.byref(name_size))
                    device_path = name_buffer.value
                    handle_int = dev.hDevice if isinstance(dev.hDevice, int) else ctypes.cast(dev.hDevice, ctypes.c_void_p).value or 0
                    self._device_paths[handle_int] = device_path
                    log.debug(f"Found mouse device: handle={handle_int}, path={device_path}")

    def _run(self):
        """Main thread - create window and process messages."""
        # Enumerate devices first
        self._enumerate_devices()
        log.info(f"Found {len(self._device_paths)} mouse devices via Raw Input")

        # Create a message-only window
        hinstance = kernel32.GetModuleHandleW(None)
        class_name = "AutoMouseRawInput"

        def wndproc(hwnd, msg, wparam, lparam):
            if msg == WM_INPUT:
                self._handle_raw_input(lparam)
            elif msg == WM_DESTROY:
                user32.PostQuitMessage(0)
            return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

        self._wndproc = WNDPROC(wndproc)

        wc = WNDCLASSEX()
        wc.cbSize = ctypes.sizeof(WNDCLASSEX)
        wc.lpfnWndProc = self._wndproc
        wc.hInstance = hinstance
        wc.lpszClassName = class_name

        if not user32.RegisterClassExW(ctypes.byref(wc)):
            log.error("Failed to register window class")
            return

        # HWND_MESSAGE = -3 for message-only window
        HWND_MESSAGE = wintypes.HWND(-3)
        self._hwnd = user32.CreateWindowExW(
            0, class_name, "AutoMouse Raw Input",
            0, 0, 0, 0, 0,
            HWND_MESSAGE, None, hinstance, None
        )

        if not self._hwnd:
            log.error("Failed to create message window")
            return

        # Register for raw input
        rid = RAWINPUTDEVICE()
        rid.usUsagePage = 0x01  # Generic Desktop
        rid.usUsage = 0x02      # Mouse
        rid.dwFlags = RIDEV_INPUTSINK  # Receive input even when not focused
        rid.hwndTarget = self._hwnd

        if not user32.RegisterRawInputDevices(ctypes.byref(rid), 1, ctypes.sizeof(rid)):
            log.error("Failed to register for raw input")
            return

        log.info("Raw Input monitoring started")

        # Message loop
        msg = wintypes.MSG()
        while self._running:
            if user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 1):  # PM_REMOVE = 1
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))
            else:
                time.sleep(0.001)  # Don't spin

        user32.DestroyWindow(self._hwnd)
        user32.UnregisterClassW(class_name, hinstance)

    def _handle_raw_input(self, lparam):
        """Process a WM_INPUT message."""
        try:
            # Get size
            size = wintypes.UINT()
            user32.GetRawInputData(lparam, RID_INPUT, None, ctypes.byref(size), ctypes.sizeof(RAWINPUTHEADER))

            if size.value == 0:
                return

            # Get data
            buffer = ctypes.create_string_buffer(size.value)
            user32.GetRawInputData(lparam, RID_INPUT, buffer, ctypes.byref(size), ctypes.sizeof(RAWINPUTHEADER))

            raw = ctypes.cast(buffer, ctypes.POINTER(RAWINPUT)).contents

            if raw.header.dwType == RIM_TYPEMOUSE:
                # Check if there was actual movement or button activity
                mouse = raw.data.mouse
                if mouse.lLastX != 0 or mouse.lLastY != 0 or mouse.usButtonFlags != 0:
                    handle = raw.header.hDevice
                    handle_int = handle if isinstance(handle, int) else ctypes.cast(handle, ctypes.c_void_p).value or 0

                    if handle_int in self._device_paths:
                        self._on_activity(self._device_paths[handle_int])
                    else:
                        # Device might be newly connected, re-enumerate
                        self._enumerate_devices()
                        if handle_int in self._device_paths:
                            self._on_activity(self._device_paths[handle_int])
        except Exception as e:
            log.debug(f"Error processing raw input: {e}")
