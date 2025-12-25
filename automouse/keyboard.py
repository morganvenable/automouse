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

import keyboard as kb  # The keyboard library - reliable Windows hooks
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

# Modifier key names to pass through
MODIFIER_NAMES = {'shift', 'ctrl', 'alt', 'left shift', 'right shift',
                  'left ctrl', 'right ctrl', 'left alt', 'right alt',
                  'left windows', 'right windows'}


class KeyboardController:
    """
    Handles keyboard interception and mouse action injection.

    Uses the 'keyboard' library for hooks (better Windows support)
    and pynput for mouse actions.
    """

    def __init__(self):
        self._mappings: Dict[str, MouseAction] = {}
        self._mouse_listener = None
        self._mouse_controller = mouse.Controller()

        self._layer_active = False
        self._exit_on_unmapped = True
        self._held_keys: Set[str] = set()

        # Callbacks
        self._on_mouse_activity: Optional[Callable[[], None]] = None
        self._on_mapped_key: Optional[Callable[[], None]] = None
        self._on_unmapped_key: Optional[Callable[[], None]] = None

        # Worker thread for slow operations
        self._action_queue: queue.Queue = queue.Queue()
        self._worker_thread: Optional[threading.Thread] = None
        self._running = False

        # Keyboard hook handle
        self._hook_installed = False

    def set_mappings(self, mappings: Dict[str, str]):
        self._mappings = {}
        for key_str, action_str in mappings.items():
            action = ACTION_MAP.get(action_str.lower())
            if action:
                # Normalize key name for 'keyboard' library
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
            if not active:
                self._held_keys.clear()

    def set_exit_on_unmapped(self, exit_on_unmapped: bool):
        self._exit_on_unmapped = exit_on_unmapped

    def _on_key_event(self, event):
        """
        Handle keyboard events from the 'keyboard' library.

        This runs in the hook thread - must be fast!
        Return True to suppress the key, False to pass through.
        """
        try:
            key_name = event.name.lower() if event.name else None
            is_down = event.event_type == 'down'

            # Layer not active - pass through
            if not self._layer_active:
                return False

            if not key_name:
                return False

            # Modifiers pass through
            if key_name in MODIFIER_NAMES:
                return False

            if is_down:
                # Key repeat - suppress but don't re-trigger action
                if key_name in self._held_keys:
                    return True  # Suppress repeat

                # Mapped key?
                if key_name in self._mappings:
                    self._held_keys.add(key_name)
                    action = self._mappings[key_name]
                    self._action_queue.put_nowait(('press', key_name, action))
                    return True  # Suppress

                # Unmapped key - pass through but maybe exit layer
                if self._exit_on_unmapped:
                    self._action_queue.put_nowait(('unmapped',))
                return False

            else:  # key up
                if key_name in self._held_keys:
                    self._held_keys.discard(key_name)
                    action = self._mappings.get(key_name)
                    if action:
                        self._action_queue.put_nowait(('release', key_name, action))
                    return True  # Suppress release too

                return False

        except Exception as e:
            log.error(f"Key event error: {e}")
            return False

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

                elif cmd == 'unmapped':
                    if self._on_unmapped_key:
                        self._on_unmapped_key()

                elif cmd == 'mouse_activity':
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
            self._action_queue.put_nowait(('mouse_activity',))
        except:
            pass

    def _on_mouse_click(self, x, y, button, pressed):
        try:
            self._action_queue.put_nowait(('mouse_activity',))
        except:
            pass

    def _on_mouse_scroll(self, x, y, dx, dy):
        try:
            self._action_queue.put_nowait(('mouse_activity',))
        except:
            pass

    def start(self):
        """Start listeners."""
        self._running = True

        # Start worker thread
        self._worker_thread = threading.Thread(target=self._worker_loop, daemon=True)
        self._worker_thread.start()

        # Install keyboard hook using 'keyboard' library
        # suppress=True means the callback can return True to block keys
        kb.hook(self._on_key_event, suppress=True)
        self._hook_installed = True
        log.info("Keyboard hook installed")

        # Mouse listener (pynput - just for monitoring, not control)
        self._mouse_listener = mouse.Listener(
            on_move=self._on_mouse_move,
            on_click=self._on_mouse_click,
            on_scroll=self._on_mouse_scroll
        )
        self._mouse_listener.start()
        log.info("Mouse listener started")

    def stop(self):
        """Stop listeners."""
        log.info("Stopping...")
        self._running = False

        if self._hook_installed:
            kb.unhook_all()
            self._hook_installed = False

        if self._mouse_listener:
            self._mouse_listener.stop()
            self._mouse_listener = None

        if self._worker_thread:
            self._worker_thread.join(timeout=1.0)
            self._worker_thread = None

        log.info("Stopped")
