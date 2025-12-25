"""
AutoMouse - Main entry point and system tray daemon.
"""

import sys
import os
import logging
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
from .hid_monitor import enumerate_pointing_devices, enumerate_all_devices, HID_AVAILABLE

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s.%(msecs)03d [%(levelname)s] %(name)s: %(message)s',
    datefmt='%H:%M:%S'
)
log = logging.getLogger(__name__)


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
        log.info("Loading configuration...")
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

        log.info(f"Layer config: timeout={timeout}ms, exit_on_unmapped={exit_on_unmapped}")
        log.info(f"Key mappings: {mappings}")

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
        log.info(f"State change: {change.old_state.name} -> {change.new_state.name} (reason: {change.reason})")

        if self.keyboard:
            is_active = change.new_state in (
                LayerState.MOUSE_LAYER_ACTIVE,
                LayerState.LATCHED
            )
            self.keyboard.set_layer_active(is_active)

        # Update tray icon if available
        self._update_tray_icon()

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
        except Exception as e:
            log.error(f"Error updating tray icon: {e}")

    def _create_menu(self):
        """Create the system tray menu."""
        if not TRAY_AVAILABLE:
            return None

        def get_status(item):
            if self.state_machine:
                return f"Status: {self.state_machine.state.name}"
            return "Status: Unknown"

        def open_config(icon, item):
            config_path = get_config_path()
            log.info(f"Opening config: {config_path}")
            if sys.platform == 'win32':
                os.startfile(config_path)
            elif sys.platform == 'darwin':
                os.system(f'open "{config_path}"')
            else:
                os.system(f'xdg-open "{config_path}"')

        def reload_config(icon, item):
            log.info("Reloading configuration...")
            self.load_config()
            log.info("Configuration reloaded")

        def show_devices(icon, item):
            log.info("=" * 60)
            log.info("HID DEVICE ENUMERATION")
            log.info("=" * 60)

            try:
                if not HID_AVAILABLE:
                    log.warning("hidapi not available. Install with: pip install hidapi")
                    log.warning("On Windows, you may also need to install hidapi DLL.")
                else:
                    # Show all HID devices
                    all_devices = enumerate_all_devices()
                    if all_devices:
                        log.info(f"Found {len(all_devices)} HID devices:")
                        for d in all_devices:
                            is_mouse = d.is_pointing_device
                            marker = " [POINTING DEVICE]" if is_mouse else ""
                            name = d.product or d.manufacturer or "Unknown"
                            log.info(f"  {name}{marker}")
                            log.info(f"    VID:0x{d.vid:04X} PID:0x{d.pid:04X}")
                            log.info(f"    Usage Page: 0x{d.usage_page:04X} Usage: 0x{d.usage:02X}")
                    else:
                        log.info("No HID devices found.")
                        log.info("This may be normal on Windows - mice are often exclusively owned by the OS.")

                log.info("Note: AutoMouse uses pynput for mouse activity detection,")
                log.info("which works with any mouse without needing raw HID access.")
                log.info("=" * 60)
            except Exception as e:
                log.error(f"Error in show_devices: {e}")

        def quit_app(icon, item):
            log.info("Quit requested from tray menu")
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

        log.info("="*60)
        log.info("AutoMouse starting...")
        log.info("="*60)

        # Load configuration
        self.load_config()

        # Start keyboard/mouse listeners
        if self.keyboard:
            self.keyboard.start()

        config_path = get_config_path()
        log.info(f"Config file: {config_path}")
        print(f"\nAutoMouse started!")
        print(f"Config: {config_path}")
        if self.config and self.config.layers:
            layer = list(self.config.layers.values())[0]
            print(f"Timeout: {layer.timeout_ms}ms")
            print(f"Mappings: {list(layer.mappings.keys())}")
        print("\nMove your mouse to activate the layer, then press mapped keys.")
        print("Check the console for detailed logs.\n")

        # Start system tray if available
        if TRAY_AVAILABLE:
            log.info("Starting system tray...")
            self.tray = pystray.Icon(
                'automouse',
                self._create_icon(active=False),
                'AutoMouse',
                menu=self._create_menu()
            )
            self.tray.run()  # This blocks until quit
        else:
            log.warning("System tray not available, running in console mode")
            print("Press Ctrl+C to quit")
            try:
                while self._running:
                    threading.Event().wait(1)
            except KeyboardInterrupt:
                pass

        self.stop()

    def stop(self):
        """Stop the daemon."""
        log.info("Stopping AutoMouse...")
        self._running = False

        if self.keyboard:
            self.keyboard.stop()

        if self.tray:
            self.tray.stop()

        log.info("AutoMouse stopped")


def main():
    """Main entry point."""
    app = AutoMouse()

    try:
        app.start()
    except KeyboardInterrupt:
        app.stop()
    except Exception as e:
        log.exception(f"Fatal error: {e}")
        sys.exit(1)


if __name__ == '__main__':
    main()
