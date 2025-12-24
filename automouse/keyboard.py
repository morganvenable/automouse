"""
Keyboard event interception and injection.

Uses pynput for cross-platform keyboard hooks and event injection.
"""

import threading
from typing import Callable, Dict, Optional, Set
from dataclasses import dataclass
from enum import Enum, auto

from pynput import keyboard, mouse
from pynput.keyboard import Key, KeyCode
from pynput.mouse import Button


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


def string_to_key(s: str):
    """Convert a string to a pynput key."""
    s = s.lower()

    # Check if it's a special key
    try:
        return Key[s]
    except KeyError:
        pass

    # Single character
    if len(s) == 1:
        return KeyCode.from_char(s)

    return None


@dataclass
class KeyMapping:
    """Represents a key-to-action mapping."""
    key: str
    action: MouseAction


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
        self._keyboard_controller = keyboard.Controller()

        self._layer_active = False
        self._exit_on_unmapped = True
        self._pressed_keys: Set[str] = set()
        self._suppressed_keys: Set[str] = set()

        # Callbacks
        self._on_mouse_activity: Optional[Callable[[], None]] = None
        self._on_mapped_key: Optional[Callable[[], None]] = None
        self._on_unmapped_key: Optional[Callable[[], None]] = None

        self._lock = threading.Lock()

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
                if not active:
                    # Release any suppressed keys
                    self._release_suppressed()

    def set_exit_on_unmapped(self, exit_on_unmapped: bool):
        """Set whether unmapped keys exit the layer."""
        self._exit_on_unmapped = exit_on_unmapped

    def _release_suppressed(self):
        """Release any keys we've been suppressing."""
        self._suppressed_keys.clear()

    def _is_modifier(self, key) -> bool:
        """Check if a key is a modifier."""
        return key in MODIFIER_KEYS

    def _on_key_press(self, key):
        """Handle key press events."""
        key_str = key_to_string(key)

        with self._lock:
            if not self._layer_active:
                return True  # Pass through

            # Modifiers always pass through
            if self._is_modifier(key):
                return True

            if key_str and key_str in self._mappings:
                # This is a mapped key - perform mouse action
                action = self._mappings[key_str]
                self._suppressed_keys.add(key_str)

                # Notify callback
                if self._on_mapped_key:
                    threading.Thread(
                        target=self._on_mapped_key,
                        daemon=True
                    ).start()

                # Perform the action in a thread to not block
                threading.Thread(
                    target=self._do_mouse_action,
                    args=(action, True),
                    daemon=True
                ).start()

                return False  # Suppress the key

            else:
                # Unmapped key
                if self._exit_on_unmapped and self._on_unmapped_key:
                    threading.Thread(
                        target=self._on_unmapped_key,
                        daemon=True
                    ).start()
                return True  # Pass through

    def _on_key_release(self, key):
        """Handle key release events."""
        key_str = key_to_string(key)

        with self._lock:
            if key_str and key_str in self._suppressed_keys:
                self._suppressed_keys.discard(key_str)

                # Release mouse button if applicable
                action = self._mappings.get(key_str)
                if action:
                    threading.Thread(
                        target=self._do_mouse_action,
                        args=(action, False),
                        daemon=True
                    ).start()

                return False  # Suppress the release too

        return True

    def _do_mouse_action(self, action: MouseAction, pressed: bool):
        """Perform a mouse action."""
        try:
            if action in BUTTON_MAP:
                button = BUTTON_MAP[action]
                if pressed:
                    self._mouse_controller.press(button)
                else:
                    self._mouse_controller.release(button)

            elif pressed:  # Scroll actions only on press, not release
                if action == MouseAction.SCROLL_UP:
                    self._mouse_controller.scroll(0, 3)
                elif action == MouseAction.SCROLL_DOWN:
                    self._mouse_controller.scroll(0, -3)
                elif action == MouseAction.SCROLL_LEFT:
                    self._mouse_controller.scroll(-3, 0)
                elif action == MouseAction.SCROLL_RIGHT:
                    self._mouse_controller.scroll(3, 0)
        except Exception:
            pass

    def _on_mouse_move(self, x, y):
        """Handle mouse movement."""
        if self._on_mouse_activity:
            self._on_mouse_activity()

    def _on_mouse_click(self, x, y, button, pressed):
        """Handle mouse clicks."""
        if self._on_mouse_activity:
            self._on_mouse_activity()

    def _on_mouse_scroll(self, x, y, dx, dy):
        """Handle mouse scroll."""
        if self._on_mouse_activity:
            self._on_mouse_activity()

    def start(self):
        """Start keyboard and mouse listeners."""
        # Keyboard listener with suppression support
        self._keyboard_listener = keyboard.Listener(
            on_press=self._on_key_press,
            on_release=self._on_key_release,
            suppress=False  # We handle suppression per-key
        )
        self._keyboard_listener.start()

        # Mouse listener for activity detection
        self._mouse_listener = mouse.Listener(
            on_move=self._on_mouse_move,
            on_click=self._on_mouse_click,
            on_scroll=self._on_mouse_scroll
        )
        self._mouse_listener.start()

    def stop(self):
        """Stop listeners."""
        if self._keyboard_listener:
            self._keyboard_listener.stop()
            self._keyboard_listener = None

        if self._mouse_listener:
            self._mouse_listener.stop()
            self._mouse_listener = None
