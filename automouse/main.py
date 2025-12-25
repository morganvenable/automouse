"""
AutoMouse - Main entry point and system tray daemon.
"""

import sys
import os
import logging
import threading
import tkinter as tk
from tkinter import ttk
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


def show_devices_dialog():
    """Show a GUI dialog with connected HID devices and live per-device activity monitor."""
    import time
    import re
    import sys
    from .config import load_config, save_config, KnownDevice

    # Load current config
    config = load_config()

    # Track activity per device - key is tree item id, value is last activity time
    device_activity = {}  # {item_id: last_activity_time}
    dialog_open = [True]
    raw_input_monitor = None

    # Mapping from VID:PID to tree item id and vice versa
    vidpid_to_item = {}  # {"046D:C52B": item_id}
    item_to_vidpid = {}  # {item_id: "046D:C52B"}
    item_to_name = {}    # {item_id: "Device Name"}

    # Track which devices have been seen active (for showing checkboxes)
    seen_active = set(config.known_devices.keys())  # Start with previously known devices

    # Create window
    root = tk.Tk()
    root.title("AutoMouse - HID Devices")
    root.geometry("750x500")
    root.resizable(True, True)

    # Configure tag styles for highlighting active devices
    style = ttk.Style()
    style.configure("Treeview", rowheight=25)

    # Create main frame with padding
    main_frame = ttk.Frame(root, padding="10")
    main_frame.pack(fill=tk.BOTH, expand=True)

    # Title label
    title = ttk.Label(main_frame, text="Connected HID Devices", font=('Segoe UI', 12, 'bold'))
    title.pack(pady=(0, 10))

    # Create frame for treeview
    tree_frame = ttk.Frame(main_frame)
    tree_frame.pack(fill=tk.BOTH, expand=True)

    # Create treeview with enabled column
    columns = ('enabled', 'activity', 'name', 'type', 'vid_pid')
    tree = ttk.Treeview(tree_frame, columns=columns, show='headings', height=12)

    tree.heading('enabled', text='Layer')
    tree.heading('activity', text='Activity')
    tree.heading('name', text='Device Name')
    tree.heading('type', text='Type')
    tree.heading('vid_pid', text='VID:PID')

    tree.column('enabled', width=50, anchor='center')
    tree.column('activity', width=80, anchor='center')
    tree.column('name', width=280)
    tree.column('type', width=120)
    tree.column('vid_pid', width=120)

    # Configure tags for active/inactive states
    tree.tag_configure('active', background='#90EE90')  # Light green
    tree.tag_configure('inactive', background='')
    tree.tag_configure('known', background='#E8F5E9')   # Very light green for known devices

    # Add scrollbar
    scrollbar = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL, command=tree.yview)
    tree.configure(yscrollcommand=scrollbar.set)

    # Pack tree and scrollbar
    tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
    scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

    def get_enabled_display(vidpid_key):
        """Get the display string for the enabled column."""
        if vidpid_key not in seen_active:
            return ''  # Not seen yet, no checkbox
        if vidpid_key in config.known_devices:
            return '☑' if config.known_devices[vidpid_key].enabled else '☐'
        return '☑'  # Default to enabled for newly seen devices

    def toggle_enabled(event):
        """Toggle the enabled state when clicking on the enabled column."""
        region = tree.identify("region", event.x, event.y)
        if region != "cell":
            return

        column = tree.identify_column(event.x)
        if column != '#1':  # First column (enabled)
            return

        item_id = tree.identify_row(event.y)
        if not item_id or item_id not in item_to_vidpid:
            return

        vidpid_key = item_to_vidpid[item_id]
        if vidpid_key not in seen_active:
            return  # Can't toggle if not seen yet

        # Toggle the state
        if vidpid_key in config.known_devices:
            config.known_devices[vidpid_key].enabled = not config.known_devices[vidpid_key].enabled
        else:
            # First toggle - add to known devices as disabled
            name = item_to_name.get(item_id, '')
            vid_str, pid_str = vidpid_key.split(':')
            config.known_devices[vidpid_key] = KnownDevice(
                vid=int(vid_str, 16),
                pid=int(pid_str, 16),
                name=name,
                enabled=False
            )

        # Update display
        tree.set(item_id, 'enabled', get_enabled_display(vidpid_key))

        # Save config in a deferred call to avoid Tkinter threading issues
        def do_save():
            try:
                save_config(config)
                log.info(f"Toggled device {vidpid_key} enabled={config.known_devices[vidpid_key].enabled}")
            except Exception as e:
                log.error(f"Failed to save config: {e}")

        root.after(10, do_save)

    tree.bind('<Button-1>', toggle_enabled)

    # Debug status label
    debug_var = tk.StringVar(value="Initializing...")
    debug_label = tk.Label(main_frame, textvariable=debug_var, font=('Consolas', 9), fg='blue')
    debug_label.pack(pady=(5, 0))

    def add_device_to_tree(vidpid_key, name, device_type, at_top=False):
        """Add a device to the tree, optionally at the top."""
        vid_display = f"0x{vidpid_key.replace(':', ':0x')}"
        enabled_display = get_enabled_display(vidpid_key)

        if at_top:
            item_id = tree.insert('', 0, values=(enabled_display, '', name, device_type, vid_display))
        else:
            item_id = tree.insert('', tk.END, values=(enabled_display, '', name, device_type, vid_display))

        device_activity[item_id] = 0.0
        vidpid_to_item[vidpid_key] = item_id
        item_to_vidpid[item_id] = vidpid_key
        item_to_name[item_id] = name
        return item_id

    # First, add known devices (from config) at the top
    known_vidpids = set()
    for vidpid_key, known_dev in config.known_devices.items():
        name = known_dev.name or f"Device ({vidpid_key})"
        add_device_to_tree(vidpid_key, name, "Mouse/Pointer", at_top=False)
        known_vidpids.add(vidpid_key)
        log.debug(f"Added known device: {vidpid_key} ({name})")

    # Then add other HID devices
    if not HID_AVAILABLE:
        if not known_vidpids:
            tree.insert('', tk.END, values=(
                '',
                '',
                'hidapi not available',
                '',
                'pip install hidapi'
            ))
    else:
        devices = enumerate_all_devices()
        if devices:
            # Deduplicate by VID:PID (devices can have multiple interfaces)
            device_map = {}  # (name, vid_pid) -> [device_objects]
            for d in devices:
                vid_pid = f"0x{d.vid:04X}:0x{d.pid:04X}"
                name = d.product or d.manufacturer or "Unknown Device"
                key = (name, vid_pid)
                if key not in device_map:
                    device_map[key] = []
                device_map[key].append(d)

            for (name, vid_pid), dev_list in device_map.items():
                vid = dev_list[0].vid
                pid = dev_list[0].pid
                vidpid_key = f"{vid:04X}:{pid:04X}"

                # Skip if already added as known device
                if vidpid_key in known_vidpids:
                    continue

                is_pointer = any(d.is_pointing_device for d in dev_list)
                device_type = "Mouse/Pointer" if is_pointer else "Other HID"
                add_device_to_tree(vidpid_key, name, device_type)
        elif not known_vidpids:
            tree.insert('', tk.END, values=(
                '',
                '',
                'No HID devices found',
                '',
                ''
            ))

    def mark_device_seen(vidpid_key, name):
        """Mark a device as seen active for the first time."""
        if vidpid_key in seen_active:
            return False  # Already seen

        seen_active.add(vidpid_key)

        # Add to known_devices in config if not already there
        if vidpid_key not in config.known_devices:
            vid_str, pid_str = vidpid_key.split(':')
            config.known_devices[vidpid_key] = KnownDevice(
                vid=int(vid_str, 16),
                pid=int(pid_str, 16),
                name=name,
                enabled=True
            )
            # Defer save to avoid threading issues
            def do_save():
                try:
                    save_config(config)
                    log.info(f"Added new known device: {vidpid_key} ({name})")
                except Exception as e:
                    log.error(f"Failed to save config: {e}")
            root.after(10, do_save)

        return True  # First time seen

    def move_to_top(item_id):
        """Move an item to the top of the tree."""
        tree.move(item_id, '', 0)

    def on_raw_input_activity(device_path: str):
        """Called when Raw Input detects activity on a specific device."""
        match = re.search(r'VID_([0-9A-Fa-f]{4})&PID_([0-9A-Fa-f]{4})', device_path)
        if match:
            vidpid_key = f"{match.group(1).upper()}:{match.group(2).upper()}"

            # If this device isn't in our map, add it dynamically
            if vidpid_key not in vidpid_to_item:
                name = f'Mouse ({vidpid_key})'
                add_device_to_tree(vidpid_key, name, 'Mouse/Pointer')
                log.info(f"Discovered new mouse via Raw Input: {vidpid_key}")

            if vidpid_key in vidpid_to_item:
                item_id = vidpid_to_item[vidpid_key]
                device_activity[item_id] = time.time()

                # First time seeing this device active?
                name = item_to_name.get(item_id, '')
                if mark_device_seen(vidpid_key, name):
                    # Move to top and update checkbox display
                    move_to_top(item_id)
                    tree.set(item_id, 'enabled', get_enabled_display(vidpid_key))

    # Try to use Windows Raw Input API for per-device detection
    if sys.platform == 'win32':
        try:
            from .rawinput import RawInputMonitor
            raw_input_monitor = RawInputMonitor(on_raw_input_activity)
            raw_input_monitor.start()
            log.info("Started Windows Raw Input monitor for per-device activity detection")
            debug_var.set("Using Windows Raw Input API - move your mouse!")
        except Exception as e:
            log.warning(f"Failed to start Raw Input monitor: {e}")
            debug_var.set(f"Raw Input failed: {e}")

    def update_display():
        """Update the activity display for all devices."""
        if not dialog_open[0]:
            return

        now = time.time()
        active_count = 0

        for item_id in list(device_activity.keys()):
            try:
                elapsed = now - device_activity.get(item_id, 0)
                vidpid_key = item_to_vidpid.get(item_id, '')

                if elapsed < 0.3:
                    tree.item(item_id, tags=('active',))
                    tree.set(item_id, 'activity', '● ACTIVE')
                    active_count += 1
                elif vidpid_key in seen_active:
                    tree.item(item_id, tags=('known',))
                    tree.set(item_id, 'activity', '')
                else:
                    tree.item(item_id, tags=('inactive',))
                    tree.set(item_id, 'activity', '')
            except Exception as e:
                log.warning(f"Display update error: {e}")

        # Update debug with activity status
        if raw_input_monitor:
            debug_var.set(f"Raw Input active, {len(seen_active)} known devices, {active_count} active now")

        root.after(50, update_display)

    def on_close():
        nonlocal debug_var
        dialog_open[0] = False
        if raw_input_monitor:
            raw_input_monitor.stop()
        # Clean up Tkinter variables before destroying to avoid thread issues
        debug_var.set("")
        debug_var = None
        root.quit()
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", on_close)

    # Info label
    info_text = "Click the Layer checkbox to enable/disable autolayer for each device."
    info_label = ttk.Label(main_frame, text=info_text, font=('Segoe UI', 9), foreground='gray')
    info_label.pack(pady=(10, 0))

    # Close button
    close_btn = ttk.Button(main_frame, text="Close", command=on_close)
    close_btn.pack(pady=(10, 0))

    # Center window on screen
    root.update_idletasks()
    width = root.winfo_width()
    height = root.winfo_height()
    x = (root.winfo_screenwidth() // 2) - (width // 2)
    y = (root.winfo_screenheight() // 2) - (height // 2)
    root.geometry(f'{width}x{height}+{x}+{y}')

    # Start the display update loop
    update_display()

    # Run dialog
    root.mainloop()


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
            # Run dialog in a separate thread to not block the tray
            threading.Thread(target=show_devices_dialog, daemon=True).start()

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
        print("Press Ctrl+Shift+Q to quit.")
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
    import signal

    app = AutoMouse()

    def signal_handler(signum, frame):
        log.info(f"Received signal {signum}, shutting down...")
        app.stop()
        sys.exit(0)

    # Register signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # Also register a global hotkey to quit (Ctrl+Shift+Q)
    try:
        import keyboard as kb
        def quit_hotkey():
            log.info("Quit hotkey pressed (Ctrl+Shift+Q)")
            app.stop()
            sys.exit(0)
        kb.add_hotkey('ctrl+shift+q', quit_hotkey, suppress=False)
        log.info("Registered quit hotkey: Ctrl+Shift+Q")
    except Exception as e:
        log.warning(f"Could not register quit hotkey: {e}")

    try:
        app.start()
    except KeyboardInterrupt:
        app.stop()
    except Exception as e:
        log.exception(f"Fatal error: {e}")
        sys.exit(1)


if __name__ == '__main__':
    main()
