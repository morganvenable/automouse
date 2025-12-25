"""
Keyboard event interception and injection.

Uses pynput for cross-platform keyboard hooks and event injection.
"""

import logging
import queue
import threading
import sys
from typing import Callable, Dict, Optional, Set
from enum import Enum, auto

from pynput import keyboard, mouse
from pynput.keyboard import Key, KeyCode
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

# Modifier keys that should pass through
MODIFIER_NAMES = {'shift', 'shift_l', 'shift_r', 'ctrl', 'ctrl_l', 'ctrl_r',
                  'alt', 'alt_l', 'alt_r', 'cmd', 'cmd_l', 'cmd_r'}


def key_to_string(key) -> Optional[str]:
    """Convert a pynput key to its string representation."""
    try:
        if isinstance(key, KeyCode):
            if key.char:
                return key.char.lower()
        elif isinstance(key, Key):
            return key.name
    except:
        pass
    return None


class KeyboardController:
    """
    Handles keyboard interception and mouse action injection.
    """

    def __init__(self):
        self._mappings: Dict[str, MouseAction] = {}
        self._keyboard_listener: Optional[keyboard.Listener] = None
        self._mouse_listener: Optional[mouse.Listener] = None
        self._mouse_controller = mouse.Controller()

        self._layer_active = False
        self._exit_on_unmapped = True

        # Track which keys are currently held down (for key repeat handling)
        self._held_keys: Set[str] = set()

        # Callbacks
        self._on_mouse_activity: Optional[Callable[[], None]] = None
        self._on_mapped_key: Optional[Callable[[], None]] = None
        self._on_unmapped_key: Optional[Callable[[], None]] = None

        # Action queue for async processing
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
            if not active:
                self._held_keys.clear()

    def set_exit_on_unmapped(self, exit_on_unmapped: bool):
        self._exit_on_unmapped = exit_on_unmapped

    def _on_key_press(self, key):
        """
        Handle key press - MUST BE ULTRA FAST on Windows.
        No exceptions can escape. Minimal work only.
        """
        # Wrap everything in try/except - any exception kills the hook on Windows
        try:
            key_str = key_to_string(key)

            # Layer not active - pass through immediately
            if not self._layer_active:
                return None  # None = pass through

            # No valid key string - pass through
            if not key_str:
                return None

            # Modifier - pass through
            if key_str in MODIFIER_NAMES:
                return None

            # Key repeat - already held, suppress without new action
            if key_str in self._held_keys:
                return False  # Suppress repeat

            # Mapped key - suppress and trigger action
            if key_str in self._mappings:
                self._held_keys.add(key_str)
                action = self._mappings[key_str]
                # Queue action - queue.put() is thread-safe and fast
                self._action_queue.put_nowait(('press', key_str, action))
                return False  # Suppress

            # Unmapped key - pass through, but notify
            if self._exit_on_unmapped:
                self._action_queue.put_nowait(('unmapped',))
            return None  # Pass through

        except:
            # Never let exceptions escape
            return None

    def _on_key_release(self, key):
        """Handle key release - MUST BE ULTRA FAST."""
        try:
            key_str = key_to_string(key)

            if not key_str:
                return None

            # Was this key being held by us?
            if key_str in self._held_keys:
                self._held_keys.discard(key_str)
                action = self._mappings.get(key_str)
                if action:
                    self._action_queue.put_nowait(('release', key_str, action))
                return False  # Suppress release

            return None  # Pass through

        except:
            return None

    def _worker_loop(self):
        """Worker thread - processes actions from queue."""
        log.info("Worker thread started")

        while self._running:
            try:
                item = self._action_queue.get(timeout=0.1)
            except queue.Empty:
                continue
            except:
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
        """Mouse movement detected."""
        try:
            self._action_queue.put_nowait(('mouse_activity',))
        except:
            pass

    def _on_mouse_click(self, x, y, button, pressed):
        """Mouse click detected."""
        try:
            self._action_queue.put_nowait(('mouse_activity',))
        except:
            pass

    def _on_mouse_scroll(self, x, y, dx, dy):
        """Mouse scroll detected."""
        try:
            self._action_queue.put_nowait(('mouse_activity',))
        except:
            pass

    def start(self):
        """Start listeners."""
        self._running = True

        # Start worker first
        self._worker_thread = threading.Thread(target=self._worker_loop, daemon=True)
        self._worker_thread.start()

        # Keyboard listener
        # Use suppress=True to intercept keys, return False to suppress, None to pass
        self._keyboard_listener = keyboard.Listener(
            on_press=self._on_key_press,
            on_release=self._on_key_release,
            suppress=True
        )
        self._keyboard_listener.start()
        log.info("Keyboard listener started (suppress=True)")

        # Mouse listener
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

        if self._keyboard_listener:
            self._keyboard_listener.stop()
            self._keyboard_listener = None

        if self._mouse_listener:
            self._mouse_listener.stop()
            self._mouse_listener = None

        if self._worker_thread:
            self._worker_thread.join(timeout=1.0)
            self._worker_thread = None

        log.info("Stopped")
