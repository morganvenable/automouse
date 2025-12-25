"""
Keyboard event interception and injection.

Uses 'keyboard' library for key hooks (reliable on Windows)
and pynput for mouse control/monitoring.
"""

import logging
import queue
import threading
from typing import Callable, Dict, Optional, Set
from enum import Enum, auto

import keyboard as kb
from pynput import mouse
from pynput.mouse import Button

log = logging.getLogger(__name__)


class MouseAction(Enum):
    """Mouse actions that can be triggered by keyboard."""
    LEFT_CLICK = auto()
    RIGHT_CLICK = auto()
    MIDDLE_CLICK = auto()
    SCROLL_UP = auto()
    SCROLL_DOWN = auto()
    SCROLL_LEFT = auto()
    SCROLL_RIGHT = auto()


# Mapping from config strings to MouseAction
ACTION_MAP = {
    'mouse_left_click': MouseAction.LEFT_CLICK,
    'mouse_right_click': MouseAction.RIGHT_CLICK,
    'mouse_middle_click': MouseAction.MIDDLE_CLICK,
    'mouse_scroll_up': MouseAction.SCROLL_UP,
    'mouse_scroll_down': MouseAction.SCROLL_DOWN,
    'mouse_scroll_left': MouseAction.SCROLL_LEFT,
    'mouse_scroll_right': MouseAction.SCROLL_RIGHT,
}

# Mapping MouseAction to pynput mouse buttons
BUTTON_MAP = {
    MouseAction.LEFT_CLICK: Button.left,
    MouseAction.RIGHT_CLICK: Button.right,
    MouseAction.MIDDLE_CLICK: Button.middle,
}


class KeyboardController:
    """
    Handles keyboard interception and mouse action injection.
    """

    def __init__(self):
        self._mappings: Dict[str, MouseAction] = {}
        self._mouse_listener = None
        self._mouse_controller = mouse.Controller()
        self._raw_input_monitor = None

        self._layer_active = False
        self._exit_on_unmapped = True
        self._held_keys: Set[str] = set()
        self._registered_hotkeys: list = []

        # Callbacks
        self._on_mouse_activity: Optional[Callable[[], None]] = None
        self._on_mapped_key: Optional[Callable[[], None]] = None
        self._on_unmapped_key: Optional[Callable[[], None]] = None

        # Device filter - callback(vidpid) -> bool, returns True if device should trigger layer
        self._device_filter: Optional[Callable[[str], bool]] = None

        # Worker thread for slow operations
        self._action_queue: queue.Queue = queue.Queue()
        self._worker_thread: Optional[threading.Thread] = None
        self._running = False

    def set_mappings(self, mappings: Dict[str, str]):
        self._mappings = {}
        for key_str, action_str in mappings.items():
            action = ACTION_MAP.get(action_str.lower())
            if action:
                self._mappings[key_str.lower()] = action
        log.info(f"Loaded {len(self._mappings)} key mappings: {list(self._mappings.keys())}")

    def set_callbacks(
        self,
        on_mouse_activity: Optional[Callable[[], None]] = None,
        on_mapped_key: Optional[Callable[[], None]] = None,
        on_unmapped_key: Optional[Callable[[], None]] = None
    ):
        self._on_mouse_activity = on_mouse_activity
        self._on_mapped_key = on_mapped_key
        self._on_unmapped_key = on_unmapped_key

    def set_layer_active(self, active: bool):
        if self._layer_active != active:
            self._layer_active = active
            log.info(f"Layer active: {active}")

            if active:
                self._register_hotkeys()
            else:
                self._unregister_hotkeys()
                self._held_keys.clear()

    def set_exit_on_unmapped(self, exit_on_unmapped: bool):
        self._exit_on_unmapped = exit_on_unmapped

    def set_device_filter(self, filter_callback: Optional[Callable[[str], bool]]):
        """Set a device filter callback. Called with VID:PID string, returns True if device should trigger layer."""
        self._device_filter = filter_callback

    def _register_hotkeys(self):
        """Register hotkeys for mapped keys when layer is active."""
        self._unregister_hotkeys()  # Clear any existing

        for key_name, action in self._mappings.items():
            try:
                # Register press handler (suppress=True blocks the key)
                hook_id = kb.on_press_key(
                    key_name,
                    lambda e, k=key_name, a=action: self._on_mapped_press(k, a),
                    suppress=True
                )
                self._registered_hotkeys.append(hook_id)

                # Register release handler
                hook_id = kb.on_release_key(
                    key_name,
                    lambda e, k=key_name, a=action: self._on_mapped_release(k, a),
                    suppress=True
                )
                self._registered_hotkeys.append(hook_id)

                log.debug(f"Registered hotkey: {key_name}")
            except Exception as e:
                log.error(f"Failed to register hotkey {key_name}: {e}")

    def _unregister_hotkeys(self):
        """Unregister all hotkeys."""
        for hook_id in self._registered_hotkeys:
            try:
                kb.unhook(hook_id)
            except:
                pass
        self._registered_hotkeys.clear()

    def _on_mapped_press(self, key_name: str, action: MouseAction):
        """Handle mapped key press."""
        try:
            # Ignore key repeats
            if key_name in self._held_keys:
                return

            self._held_keys.add(key_name)
            self._action_queue.put_nowait(('press', key_name, action))
        except:
            pass

    def _on_mapped_release(self, key_name: str, action: MouseAction):
        """Handle mapped key release."""
        try:
            if key_name in self._held_keys:
                self._held_keys.discard(key_name)
                self._action_queue.put_nowait(('release', key_name, action))
        except:
            pass

    def _worker_loop(self):
        """Worker thread for slow operations."""
        log.info("Worker thread started")

        while self._running:
            try:
                item = self._action_queue.get(timeout=0.1)
            except queue.Empty:
                continue

            try:
                cmd = item[0]

                if cmd == 'press':
                    key_str, action = item[1], item[2]
                    log.info(f"Key '{key_str}' -> {action.name}")
                    self._do_mouse_action(action, pressed=True)
                    if self._on_mapped_key:
                        self._on_mapped_key()

                elif cmd == 'release':
                    key_str, action = item[1], item[2]
                    log.debug(f"Key '{key_str}' released")
                    self._do_mouse_action(action, pressed=False)

                elif cmd == 'mouse_activity':
                    vidpid = item[1] if len(item) > 1 else None

                    # Apply device filter if set
                    if vidpid and self._device_filter:
                        if not self._device_filter(vidpid):
                            continue  # Device not enabled, skip

                    if self._on_mouse_activity:
                        self._on_mouse_activity()

            except Exception as e:
                log.error(f"Worker error: {e}")

        log.info("Worker thread stopped")

    def _do_mouse_action(self, action: MouseAction, pressed: bool):
        """Perform mouse action."""
        try:
            if action in BUTTON_MAP:
                button = BUTTON_MAP[action]
                if pressed:
                    log.info(f"Mouse {button} press")
                    self._mouse_controller.press(button)
                else:
                    log.debug(f"Mouse {button} release")
                    self._mouse_controller.release(button)
            elif pressed:
                if action == MouseAction.SCROLL_UP:
                    self._mouse_controller.scroll(0, 3)
                elif action == MouseAction.SCROLL_DOWN:
                    self._mouse_controller.scroll(0, -3)
                elif action == MouseAction.SCROLL_LEFT:
                    self._mouse_controller.scroll(-3, 0)
                elif action == MouseAction.SCROLL_RIGHT:
                    self._mouse_controller.scroll(3, 0)
        except Exception as e:
            log.error(f"Mouse action error: {e}")

    def _on_mouse_move(self, x, y):
        try:
            self._action_queue.put_nowait(('mouse_activity', None))
        except:
            pass

    def _on_mouse_click(self, x, y, button, pressed):
        try:
            self._action_queue.put_nowait(('mouse_activity', None))
        except:
            pass

    def _on_mouse_scroll(self, x, y, dx, dy):
        try:
            self._action_queue.put_nowait(('mouse_activity', None))
        except:
            pass

    def _on_raw_input_activity(self, device_path: str):
        """Called when Raw Input detects mouse activity with device path."""
        import re
        try:
            # Extract VID:PID from path like \\?\HID#VID_046D&PID_C52B&...
            match = re.search(r'VID_([0-9A-Fa-f]{4})&PID_([0-9A-Fa-f]{4})', device_path)
            if match:
                vidpid = f"{match.group(1).upper()}:{match.group(2).upper()}"
                self._action_queue.put_nowait(('mouse_activity', vidpid))
        except:
            pass

    def start(self):
        """Start listeners."""
        import sys

        self._running = True

        # Start worker thread
        self._worker_thread = threading.Thread(target=self._worker_loop, daemon=True)
        self._worker_thread.start()

        # Note: We don't install a global keyboard hook here.
        # Instead, hotkeys are registered dynamically when layer becomes active.
        log.info("Keyboard controller started (hotkeys registered on layer activation)")

        # Try to use Raw Input on Windows for per-device detection
        use_raw_input = False
        if sys.platform == 'win32':
            try:
                from .rawinput import RawInputMonitor
                self._raw_input_monitor = RawInputMonitor(self._on_raw_input_activity)
                self._raw_input_monitor.start()
                use_raw_input = True
                log.info("Using Windows Raw Input for per-device mouse detection")
            except Exception as e:
                log.warning(f"Failed to start Raw Input monitor: {e}")

        # Fallback to pynput if Raw Input not available
        if not use_raw_input:
            self._mouse_listener = mouse.Listener(
                on_move=self._on_mouse_move,
                on_click=self._on_mouse_click,
                on_scroll=self._on_mouse_scroll
            )
            self._mouse_listener.start()
            log.info("Mouse listener started (pynput fallback, no per-device filtering)")

    def stop(self):
        """Stop listeners."""
        log.info("Stopping...")
        self._running = False

        self._unregister_hotkeys()

        if self._raw_input_monitor:
            self._raw_input_monitor.stop()
            self._raw_input_monitor = None

        if self._mouse_listener:
            self._mouse_listener.stop()
            self._mouse_listener = None

        if self._worker_thread:
            self._worker_thread.join(timeout=1.0)
            self._worker_thread = None

        log.info("Stopped")
