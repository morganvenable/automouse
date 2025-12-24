"""
Keyboard event interception and injection.

Uses pynput for cross-platform keyboard hooks and event injection.
"""

import logging
import threading
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

# Modifier keys that should pass through and combine with mouse actions
MODIFIER_KEYS = {
    Key.shift, Key.shift_l, Key.shift_r,
    Key.ctrl, Key.ctrl_l, Key.ctrl_r,
    Key.alt, Key.alt_l, Key.alt_r,
    Key.cmd, Key.cmd_l, Key.cmd_r,  # macOS command key
}


def key_to_string(key) -> Optional[str]:
    """Convert a pynput key to its string representation."""
    if isinstance(key, KeyCode):
        if key.char:
            return key.char.lower()
        elif key.vk:
            # Handle special cases like numpad, etc
            return None
    elif isinstance(key, Key):
        return key.name
    return None


class KeyboardController:
    """
    Handles keyboard interception and mouse action injection.

    When the mouse layer is active:
    - Mapped keys are intercepted and converted to mouse actions
    - Unmapped keys can optionally exit the layer
    - Modifier keys pass through to combine with mouse actions
    """

    def __init__(self):
        self._mappings: Dict[str, MouseAction] = {}
        self._keyboard_listener: Optional[keyboard.Listener] = None
        self._mouse_listener: Optional[mouse.Listener] = None
        self._mouse_controller = mouse.Controller()

        self._layer_active = False
        self._exit_on_unmapped = True
        self._suppressed_keys: Set[str] = set()

        # Callbacks
        self._on_mouse_activity: Optional[Callable[[], None]] = None
        self._on_mapped_key: Optional[Callable[[], None]] = None
        self._on_unmapped_key: Optional[Callable[[], None]] = None

        self._lock = threading.RLock()

    def set_mappings(self, mappings: Dict[str, str]):
        """
        Set key mappings from config.
        mappings: dict of key_string -> action_string
        """
        self._mappings = {}
        for key_str, action_str in mappings.items():
            action = ACTION_MAP.get(action_str.lower())
            if action:
                self._mappings[key_str.lower()] = action
                log.debug(f"Mapped key '{key_str}' -> {action.name}")
        log.info(f"Loaded {len(self._mappings)} key mappings")

    def set_callbacks(
        self,
        on_mouse_activity: Optional[Callable[[], None]] = None,
        on_mapped_key: Optional[Callable[[], None]] = None,
        on_unmapped_key: Optional[Callable[[], None]] = None
    ):
        """Set event callbacks."""
        self._on_mouse_activity = on_mouse_activity
        self._on_mapped_key = on_mapped_key
        self._on_unmapped_key = on_unmapped_key

    def set_layer_active(self, active: bool):
        """Set whether the mouse layer is currently active."""
        with self._lock:
            if self._layer_active != active:
                self._layer_active = active
                log.info(f"Layer active: {active}")
                if not active:
                    # Release any suppressed keys
                    self._suppressed_keys.clear()

    def set_exit_on_unmapped(self, exit_on_unmapped: bool):
        """Set whether unmapped keys exit the layer."""
        self._exit_on_unmapped = exit_on_unmapped

    def _is_modifier(self, key) -> bool:
        """Check if a key is a modifier."""
        return key in MODIFIER_KEYS

    def _on_key_press(self, key):
        """
        Handle key press events.

        Returns False to suppress the key, True to pass through.
        NOTE: With suppress=True, we must explicitly return for every key.
        """
        key_str = key_to_string(key)
        log.debug(f"Key press: {key} -> '{key_str}' (layer_active={self._layer_active})")

        with self._lock:
            # Always pass through if layer not active
            if not self._layer_active:
                return True

            # Modifiers always pass through
            if self._is_modifier(key):
                log.debug(f"Modifier key {key}, passing through")
                return True

            # Check if it's a mapped key
            if key_str and key_str in self._mappings:
                action = self._mappings[key_str]
                self._suppressed_keys.add(key_str)
                log.info(f"Mapped key '{key_str}' -> {action.name}, suppressing")

                # Notify callback
                if self._on_mapped_key:
                    try:
                        self._on_mapped_key()
                    except Exception as e:
                        log.error(f"Error in mapped_key callback: {e}")

                # Perform the mouse action
                self._do_mouse_action(action, pressed=True)

                return False  # Suppress the key

            else:
                # Unmapped key
                log.debug(f"Unmapped key '{key_str}', passing through")
                if self._exit_on_unmapped and self._on_unmapped_key:
                    try:
                        self._on_unmapped_key()
                    except Exception as e:
                        log.error(f"Error in unmapped_key callback: {e}")
                return True  # Pass through

    def _on_key_release(self, key):
        """Handle key release events."""
        key_str = key_to_string(key)

        with self._lock:
            if key_str and key_str in self._suppressed_keys:
                self._suppressed_keys.discard(key_str)
                log.debug(f"Releasing suppressed key '{key_str}'")

                # Release mouse button if applicable
                action = self._mappings.get(key_str)
                if action:
                    self._do_mouse_action(action, pressed=False)

                return False  # Suppress the release too

        return True  # Pass through

    def _do_mouse_action(self, action: MouseAction, pressed: bool):
        """Perform a mouse action."""
        try:
            if action in BUTTON_MAP:
                button = BUTTON_MAP[action]
                if pressed:
                    log.info(f"Mouse press: {button}")
                    self._mouse_controller.press(button)
                else:
                    log.info(f"Mouse release: {button}")
                    self._mouse_controller.release(button)

            elif pressed:  # Scroll actions only on press, not release
                if action == MouseAction.SCROLL_UP:
                    log.info("Scroll up")
                    self._mouse_controller.scroll(0, 3)
                elif action == MouseAction.SCROLL_DOWN:
                    log.info("Scroll down")
                    self._mouse_controller.scroll(0, -3)
                elif action == MouseAction.SCROLL_LEFT:
                    log.info("Scroll left")
                    self._mouse_controller.scroll(-3, 0)
                elif action == MouseAction.SCROLL_RIGHT:
                    log.info("Scroll right")
                    self._mouse_controller.scroll(3, 0)
        except Exception as e:
            log.error(f"Error performing mouse action {action}: {e}")

    def _on_mouse_move(self, x, y):
        """Handle mouse movement."""
        # Don't log every movement - too noisy
        if self._on_mouse_activity:
            try:
                self._on_mouse_activity()
            except Exception as e:
                log.error(f"Error in mouse_activity callback: {e}")

    def _on_mouse_click(self, x, y, button, pressed):
        """Handle mouse clicks."""
        log.debug(f"Mouse click: {button} pressed={pressed} at ({x}, {y})")
        if self._on_mouse_activity:
            try:
                self._on_mouse_activity()
            except Exception as e:
                log.error(f"Error in mouse_activity callback: {e}")

    def _on_mouse_scroll(self, x, y, dx, dy):
        """Handle mouse scroll."""
        log.debug(f"Mouse scroll: dx={dx} dy={dy} at ({x}, {y})")
        if self._on_mouse_activity:
            try:
                self._on_mouse_activity()
            except Exception as e:
                log.error(f"Error in mouse_activity callback: {e}")

    def start(self):
        """Start keyboard and mouse listeners."""
        log.info("Starting keyboard listener with suppress=True")

        # Keyboard listener - suppress=True is required on Windows to actually
        # be able to block keys. The callback return value controls per-key suppression.
        self._keyboard_listener = keyboard.Listener(
            on_press=self._on_key_press,
            on_release=self._on_key_release,
            suppress=True
        )
        self._keyboard_listener.start()
        log.info("Keyboard listener started")

        # Mouse listener for activity detection
        self._mouse_listener = mouse.Listener(
            on_move=self._on_mouse_move,
            on_click=self._on_mouse_click,
            on_scroll=self._on_mouse_scroll
        )
        self._mouse_listener.start()
        log.info("Mouse listener started")

    def stop(self):
        """Stop listeners."""
        log.info("Stopping listeners")
        if self._keyboard_listener:
            self._keyboard_listener.stop()
            self._keyboard_listener = None

        if self._mouse_listener:
            self._mouse_listener.stop()
            self._mouse_listener = None
        log.info("Listeners stopped")
