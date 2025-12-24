"""
AutoMouse - Main entry point and system tray daemon.
"""

import sys
import os
import threading
from pathlib import Path
from typing import Optional

# Handle imports for when pystray/PIL aren't available
try:
    import pystray
    from PIL import Image, ImageDraw
    TRAY_AVAILABLE = True
except ImportError:
    TRAY_AVAILABLE = False

from .config import load_config, get_config_path, Config
from .state import LayerStateMachine, LayerState, StateChange
from .keyboard import KeyboardController
from .hid_monitor import enumerate_pointing_devices, HID_AVAILABLE


class AutoMouse:
    """Main application controller."""

    def __init__(self):
        self.config: Optional[Config] = None
        self.state_machine: Optional[LayerStateMachine] = None
        self.keyboard: Optional[KeyboardController] = None
        self.tray: Optional['pystray.Icon'] = None
        self._running = False

    def load_config(self):
        """Load or create configuration."""
        self.config = load_config()

        # Get layer config (use first layer or default)
        layer_name = list(self.config.layers.keys())[0] if self.config.layers else 'mouse_layer'
        layer_config = self.config.layers.get(layer_name)

        if layer_config:
            timeout = layer_config.timeout_ms
            mappings = layer_config.mappings
            exit_on_unmapped = layer_config.exit_on_other_key
        else:
            timeout = 900
            mappings = {
                'j': 'mouse_left_click',
                'k': 'mouse_right_click',
                'u': 'mouse_scroll_up',
                'i': 'mouse_scroll_down',
            }
            exit_on_unmapped = True

        # Initialize state machine
        self.state_machine = LayerStateMachine(timeout_ms=timeout)
        self.state_machine.add_listener(self._on_state_change)

        # Initialize keyboard controller
        self.keyboard = KeyboardController()
        self.keyboard.set_mappings(mappings)
        self.keyboard.set_exit_on_unmapped(exit_on_unmapped)
        self.keyboard.set_callbacks(
            on_mouse_activity=self._on_mouse_activity,
            on_mapped_key=self._on_mapped_key,
            on_unmapped_key=self._on_unmapped_key
        )

    def _on_mouse_activity(self):
        """Called when mouse/pointing device activity is detected."""
        if self.state_machine:
            self.state_machine.on_mouse_activity()

    def _on_mapped_key(self):
        """Called when a mapped key is pressed."""
        if self.state_machine:
            self.state_machine.on_mapped_key()

    def _on_unmapped_key(self):
        """Called when an unmapped key is pressed."""
        if self.state_machine:
            self.state_machine.on_unmapped_key()

    def _on_state_change(self, change: StateChange):
        """Called when layer state changes."""
        if self.keyboard:
            is_active = change.new_state in (
                LayerState.MOUSE_LAYER_ACTIVE,
                LayerState.LATCHED
            )
            self.keyboard.set_layer_active(is_active)

        # Update tray icon if available
        self._update_tray_icon()

        # Log state change
        state_name = change.new_state.name
        print(f"Layer state: {state_name} (reason: {change.reason})")

    def _create_icon(self, active: bool = False) -> 'Image.Image':
        """Create tray icon image."""
        size = 64
        img = Image.new('RGBA', (size, size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)

        # Background circle
        bg_color = (76, 175, 80, 255) if active else (158, 158, 158, 255)
        draw.ellipse([4, 4, size-4, size-4], fill=bg_color)

        # Mouse icon (simplified)
        mouse_color = (255, 255, 255, 255)
        # Body
        draw.ellipse([18, 20, 46, 52], fill=mouse_color)
        # Ears
        draw.ellipse([14, 16, 26, 28], fill=mouse_color)
        draw.ellipse([38, 16, 50, 28], fill=mouse_color)
        # Button line
        draw.line([32, 24, 32, 38], fill=bg_color, width=2)

        return img

    def _update_tray_icon(self):
        """Update the tray icon based on current state."""
        if not TRAY_AVAILABLE or not self.tray:
            return

        try:
            is_active = (
                self.state_machine and
                self.state_machine.state != LayerState.NORMAL
            )
            self.tray.icon = self._create_icon(active=is_active)
        except Exception:
            pass

    def _create_menu(self):
        """Create the system tray menu."""
        if not TRAY_AVAILABLE:
            return None

        def get_status():
            if self.state_machine:
                return f"Status: {self.state_machine.state.name}"
            return "Status: Unknown"

        def open_config(icon, item):
            config_path = get_config_path()
            if sys.platform == 'win32':
                os.startfile(config_path)
            elif sys.platform == 'darwin':
                os.system(f'open "{config_path}"')
            else:
                os.system(f'xdg-open "{config_path}"')

        def reload_config(icon, item):
            self.load_config()
            print("Configuration reloaded")

        def show_devices(icon, item):
            devices = enumerate_pointing_devices()
            if devices:
                print("\nConnected pointing devices:")
                for d in devices:
                    print(f"  {d.product or 'Unknown'} (VID:{d.vid:04x} PID:{d.pid:04x})")
            else:
                print("\nNo pointing devices found (or hidapi not available)")

        def quit_app(icon, item):
            self.stop()

        return pystray.Menu(
            pystray.MenuItem(get_status, None, enabled=False),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Show Devices", show_devices),
            pystray.MenuItem("Open Config", open_config),
            pystray.MenuItem("Reload Config", reload_config),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit", quit_app)
        )

    def start(self):
        """Start the daemon."""
        self._running = True

        # Load configuration
        self.load_config()

        # Start keyboard/mouse listeners
        if self.keyboard:
            self.keyboard.start()

        print("AutoMouse started")
        print(f"Config: {get_config_path()}")
        if self.config and self.config.layers:
            layer = list(self.config.layers.values())[0]
            print(f"Timeout: {layer.timeout_ms}ms")
            print(f"Mappings: {list(layer.mappings.keys())}")

        # Start system tray if available
        if TRAY_AVAILABLE:
            self.tray = pystray.Icon(
                'automouse',
                self._create_icon(active=False),
                'AutoMouse',
                menu=self._create_menu()
            )
            self.tray.run()  # This blocks until quit
        else:
            print("System tray not available, running in console mode")
            print("Press Ctrl+C to quit")
            try:
                while self._running:
                    threading.Event().wait(1)
            except KeyboardInterrupt:
                pass

        self.stop()

    def stop(self):
        """Stop the daemon."""
        self._running = False

        if self.keyboard:
            self.keyboard.stop()

        if self.tray:
            self.tray.stop()

        print("AutoMouse stopped")


def main():
    """Main entry point."""
    app = AutoMouse()

    try:
        app.start()
    except KeyboardInterrupt:
        app.stop()
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)


if __name__ == '__main__':
    main()
