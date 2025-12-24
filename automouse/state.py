"""
Layer state machine.

States:
- normal: Keyboard behaves normally
- mouse_layer_active: Keys emit mouse actions
- latched: Layer persists until explicitly exited
"""

import time
import threading
from enum import Enum, auto
from typing import Callable, Optional, List
from dataclasses import dataclass


class LayerState(Enum):
    NORMAL = auto()
    MOUSE_LAYER_ACTIVE = auto()
    LATCHED = auto()


@dataclass
class StateChange:
    """Represents a state transition."""
    old_state: LayerState
    new_state: LayerState
    reason: str
    timestamp: float


class LayerStateMachine:
    """
    Manages the global layer state across devices.

    The state machine handles transitions triggered by:
    - Pointing device motion or buttons
    - Explicit exit keys
    - Inactivity timeout
    """

    def __init__(self, timeout_ms: int = 900):
        self._state = LayerState.NORMAL
        self._timeout_ms = timeout_ms
        self._last_activity = 0.0
        self._timer: Optional[threading.Timer] = None
        self._lock = threading.Lock()
        self._listeners: List[Callable[[StateChange], None]] = []

    @property
    def state(self) -> LayerState:
        """Current layer state."""
        with self._lock:
            return self._state

    @property
    def is_active(self) -> bool:
        """True if mouse layer is active (either active or latched)."""
        return self._state in (LayerState.MOUSE_LAYER_ACTIVE, LayerState.LATCHED)

    @property
    def timeout_ms(self) -> int:
        """Get the timeout in milliseconds."""
        return self._timeout_ms

    @timeout_ms.setter
    def timeout_ms(self, value: int):
        """Set the timeout in milliseconds. 0 or negative means infinite."""
        self._timeout_ms = value

    def add_listener(self, callback: Callable[[StateChange], None]):
        """Add a state change listener."""
        self._listeners.append(callback)

    def remove_listener(self, callback: Callable[[StateChange], None]):
        """Remove a state change listener."""
        if callback in self._listeners:
            self._listeners.remove(callback)

    def _notify_listeners(self, change: StateChange):
        """Notify all listeners of a state change."""
        for listener in self._listeners:
            try:
                listener(change)
            except Exception:
                pass  # Don't let listener errors break state machine

    def _cancel_timer(self):
        """Cancel any pending timeout timer."""
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None

    def _start_timer(self):
        """Start the inactivity timeout timer."""
        self._cancel_timer()

        if self._timeout_ms <= 0:
            return  # Infinite timeout (latched mode)

        self._timer = threading.Timer(
            self._timeout_ms / 1000.0,
            self._on_timeout
        )
        self._timer.daemon = True
        self._timer.start()

    def _on_timeout(self):
        """Called when the inactivity timer fires."""
        with self._lock:
            if self._state == LayerState.MOUSE_LAYER_ACTIVE:
                self._transition_to(LayerState.NORMAL, "timeout")

    def _transition_to(self, new_state: LayerState, reason: str):
        """Internal state transition (must hold lock)."""
        if new_state == self._state:
            return

        old_state = self._state
        self._state = new_state

        change = StateChange(
            old_state=old_state,
            new_state=new_state,
            reason=reason,
            timestamp=time.time()
        )

        # Schedule listener notification outside lock
        threading.Thread(
            target=self._notify_listeners,
            args=(change,),
            daemon=True
        ).start()

    def on_mouse_activity(self):
        """
        Called when pointing device motion or button activity is detected.
        Activates or extends the mouse layer.
        """
        with self._lock:
            self._last_activity = time.time()

            if self._state == LayerState.NORMAL:
                self._transition_to(LayerState.MOUSE_LAYER_ACTIVE, "mouse_activity")
                self._start_timer()
            elif self._state == LayerState.MOUSE_LAYER_ACTIVE:
                # Reset the timeout timer
                self._start_timer()
            # LATCHED state: no action needed, stays latched

    def on_mapped_key(self):
        """
        Called when a key that's mapped in the mouse layer is pressed.
        Resets the inactivity timer but doesn't change state.
        """
        with self._lock:
            if self._state == LayerState.MOUSE_LAYER_ACTIVE:
                self._last_activity = time.time()
                self._start_timer()

    def on_unmapped_key(self):
        """
        Called when an unmapped key is pressed.
        Exits the mouse layer if exit_on_other_key is enabled.
        """
        with self._lock:
            if self._state == LayerState.MOUSE_LAYER_ACTIVE:
                self._cancel_timer()
                self._transition_to(LayerState.NORMAL, "unmapped_key")

    def latch(self):
        """
        Latch the mouse layer so it persists until explicitly exited.
        """
        with self._lock:
            if self._state in (LayerState.NORMAL, LayerState.MOUSE_LAYER_ACTIVE):
                self._cancel_timer()
                self._transition_to(LayerState.LATCHED, "latch")

    def exit_layer(self):
        """
        Explicitly exit the mouse layer.
        """
        with self._lock:
            self._cancel_timer()
            if self._state != LayerState.NORMAL:
                self._transition_to(LayerState.NORMAL, "explicit_exit")

    def reset(self):
        """Reset to normal state."""
        self.exit_layer()
