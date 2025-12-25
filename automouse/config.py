"""
Configuration loading and management.
"""

import os
import yaml
from pathlib import Path
from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class KnownDevice:
    """A device that has been seen and can trigger the layer."""
    vid: int
    pid: int
    name: str = ""
    enabled: bool = True  # Whether this device triggers the autolayer


@dataclass
class DeviceConfig:
    """Configuration for a single HID device."""
    vid: int
    pid: int
    role: str  # 'trigger' or 'target'
    name: Optional[str] = None


@dataclass
class LayerConfig:
    """Configuration for a mouse layer."""
    timeout_ms: int = 900
    mappings: Dict[str, str] = field(default_factory=dict)
    exit_on_other_key: bool = True


@dataclass
class Config:
    """Main application configuration."""
    devices: Dict[str, DeviceConfig] = field(default_factory=dict)
    layers: Dict[str, LayerConfig] = field(default_factory=dict)
    known_devices: Dict[str, KnownDevice] = field(default_factory=dict)  # VID:PID -> KnownDevice

    # Global settings
    any_pointing_device: bool = True  # Use any mouse/trackball as trigger
    any_keyboard: bool = True  # Use any keyboard as target


def get_config_path() -> Path:
    """Get the configuration file path."""
    if os.name == 'nt':  # Windows
        base = Path(os.environ.get('APPDATA', '~'))
    elif os.name == 'posix':
        if 'darwin' in os.uname().sysname.lower():  # macOS
            base = Path.home() / 'Library' / 'Application Support'
        else:  # Linux
            base = Path(os.environ.get('XDG_CONFIG_HOME', Path.home() / '.config'))
    else:
        base = Path.home()

    return base / 'automouse' / 'config.yaml'


def parse_hex(value) -> int:
    """Parse a hex string or int to int."""
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        return int(value, 16) if value.startswith('0x') else int(value)
    raise ValueError(f"Cannot parse {value} as hex")


def load_config(path: Optional[Path] = None) -> Config:
    """Load configuration from YAML file."""
    if path is None:
        path = get_config_path()

    if not path.exists():
        return create_default_config(path)

    with open(path, 'r') as f:
        data = yaml.safe_load(f) or {}

    config = Config()

    # Parse devices
    for name, dev_data in data.get('devices', {}).items():
        config.devices[name] = DeviceConfig(
            vid=parse_hex(dev_data.get('vid', 0)),
            pid=parse_hex(dev_data.get('pid', 0)),
            role=dev_data.get('role', 'trigger'),
            name=dev_data.get('name', name)
        )

    # Parse layers
    for name, layer_data in data.get('layers', {}).items():
        config.layers[name] = LayerConfig(
            timeout_ms=layer_data.get('timeout_ms', 900),
            mappings=layer_data.get('mappings', {}),
            exit_on_other_key=layer_data.get('exit_on_other_key', True)
        )

    # Parse known devices (VID:PID -> settings)
    for vidpid, dev_data in data.get('known_devices', {}).items():
        # Parse VID:PID string like "093A:2510"
        try:
            vid_str, pid_str = vidpid.split(':')
            vid = int(vid_str, 16)
            pid = int(pid_str, 16)
            config.known_devices[vidpid] = KnownDevice(
                vid=vid,
                pid=pid,
                name=dev_data.get('name', ''),
                enabled=dev_data.get('enabled', True)
            )
        except (ValueError, AttributeError):
            pass  # Skip malformed entries

    # Global settings
    config.any_pointing_device = data.get('any_pointing_device', True)
    config.any_keyboard = data.get('any_keyboard', True)

    return config


def create_default_config(path: Path) -> Config:
    """Create and save a default configuration."""
    default_yaml = """# AutoMouse Configuration

# When true, any mouse/trackball movement activates the mouse layer
any_pointing_device: true

# When true, remap keys on any connected keyboard
any_keyboard: true

# Device-specific configuration (optional - use if you want to limit to specific devices)
devices: {}

# Layer configuration
layers:
  mouse_layer:
    timeout_ms: 500  # Layer deactivates after this many ms of no mouse movement
    exit_on_other_key: true  # Any non-mapped key exits the layer
    mappings:
      # Home row mouse buttons
      f: mouse_left_click
      s: mouse_right_click
      d: mouse_middle_click

      # Scroll keys
      x: keyboard_control_x
      c: keyboard_control_c
      v: keyboard_control_v

      # Modifier combinations work normally (shift+j = shift+left_click for drag)
"""

    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, 'w') as f:
        f.write(default_yaml)

    return load_config(path)


def save_config(config: Config, path: Optional[Path] = None):
    """Save configuration to YAML file."""
    if path is None:
        path = get_config_path()

    data = {
        'any_pointing_device': config.any_pointing_device,
        'any_keyboard': config.any_keyboard,
        'devices': {},
        'layers': {},
        'known_devices': {}
    }

    for name, dev in config.devices.items():
        data['devices'][name] = {
            'vid': hex(dev.vid),
            'pid': hex(dev.pid),
            'role': dev.role,
            'name': dev.name
        }

    for name, layer in config.layers.items():
        data['layers'][name] = {
            'timeout_ms': layer.timeout_ms,
            'mappings': layer.mappings,
            'exit_on_other_key': layer.exit_on_other_key
        }

    # Save known devices with their enabled state
    for vidpid, dev in config.known_devices.items():
        data['known_devices'][vidpid] = {
            'name': dev.name,
            'enabled': dev.enabled
        }

    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, 'w') as f:
        yaml.dump(data, f, default_flow_style=False)
