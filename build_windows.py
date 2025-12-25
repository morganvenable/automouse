#!/usr/bin/env python3
"""
Build script for creating a Windows executable using Nuitka.

Nuitka compiles Python to C, resulting in fewer antivirus false positives
compared to PyInstaller.

Requirements:
    pip install nuitka ordered-set zstandard

For best results, also install:
    - MinGW-w64 (or Visual Studio with C++ tools)
    - Inno Setup 6 (for creating the installer)

Usage:
    python build_windows.py
"""

import subprocess
import sys
import shutil
from pathlib import Path

# Build configuration
APP_NAME = "AutoMouse"
APP_VERSION = "1.0.0"
COMPANY_NAME = "AutoMouse"
DESCRIPTION = "Cross-platform cooperative HID device behavior daemon"
MAIN_SCRIPT = "automouse/__main__.py"

def check_requirements():
    """Check if build requirements are installed."""
    # Check Nuitka
    try:
        import nuitka
        # Get version via command line since nuitka doesn't expose __version__
        result = subprocess.run([sys.executable, "-m", "nuitka", "--version"],
                                capture_output=True, text=True)
        version = result.stdout.strip().split('\n')[0] if result.returncode == 0 else "unknown"
        print(f"✓ Nuitka found ({version})")
    except ImportError:
        print("✗ Nuitka not found. Install with: pip install nuitka ordered-set zstandard")
        return False

    # Check if we have a C compiler
    if shutil.which("gcc") or shutil.which("cl"):
        print("✓ C compiler found")
    else:
        print("⚠ No C compiler found. Install MinGW-w64 or Visual Studio Build Tools")
        print("  MinGW-w64: https://www.mingw-w64.org/downloads/")
        return False

    return True


def build():
    """Build the executable with Nuitka."""
    if not check_requirements():
        sys.exit(1)

    print(f"\nBuilding {APP_NAME} v{APP_VERSION}...")

    # Output directory
    dist_dir = Path("dist")
    dist_dir.mkdir(exist_ok=True)

    # Nuitka command with AV-friendly settings
    cmd = [
        sys.executable, "-m", "nuitka",

        # Output settings - standalone (NOT onefile, less AV triggers)
        "--standalone",
        f"--output-dir={dist_dir}",
        f"--output-filename={APP_NAME}.exe",

        # Windows-specific settings
        "--windows-console-mode=attach",  # Show console when run from terminal
        "--windows-icon-from-ico=assets/icon.ico" if Path("assets/icon.ico").exists() else "",

        # Company/product info (helps with AV reputation)
        f"--windows-company-name={COMPANY_NAME}",
        f"--windows-product-name={APP_NAME}",
        f"--windows-file-version={APP_VERSION}",
        f"--windows-product-version={APP_VERSION}",
        f"--windows-file-description={DESCRIPTION}",

        # Include necessary packages
        "--include-package=automouse",
        "--include-package=pynput",
        "--include-package=keyboard",
        "--include-package=pystray",
        "--include-package=PIL",
        "--include-package=yaml",
        "--include-package=hid",

        # Follow imports
        "--follow-imports",

        # Disable some things that trigger AV
        "--assume-yes-for-downloads",  # Auto-download dependencies

        # Plugin for tk/tcl (needed for tkinter dialogs)
        "--enable-plugin=tk-inter",

        # Main script
        MAIN_SCRIPT,
    ]

    # Remove empty strings from command
    cmd = [c for c in cmd if c]

    print("\nRunning Nuitka...")
    print(" ".join(cmd))
    print()

    result = subprocess.run(cmd)

    if result.returncode == 0:
        output_dir = dist_dir / f"{MAIN_SCRIPT.replace('/', '.').replace('.py', '')}.dist"
        print(f"\n✓ Build successful!")
        print(f"  Output: {output_dir}")
        print(f"\nNext steps:")
        print(f"  1. Test the executable: {output_dir}/{APP_NAME}.exe")
        print(f"  2. Run build_installer.py to create the installer")
    else:
        print(f"\n✗ Build failed with code {result.returncode}")
        sys.exit(1)


if __name__ == "__main__":
    build()
