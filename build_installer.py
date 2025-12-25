#!/usr/bin/env python3
"""
Build the Windows installer using Inno Setup.

Requirements:
    - Inno Setup 6 installed: https://jrsoftware.org/isinfo.php
    - Run build_windows.py first to create the Nuitka build

Usage:
    python build_installer.py
"""

import subprocess
import sys
import shutil
from pathlib import Path


def find_inno_setup():
    """Find the Inno Setup compiler."""
    # Common installation paths
    paths = [
        r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
        r"C:\Program Files\Inno Setup 6\ISCC.exe",
        r"C:\Program Files (x86)\Inno Setup 5\ISCC.exe",
        r"C:\Program Files\Inno Setup 5\ISCC.exe",
    ]

    for path in paths:
        if Path(path).exists():
            return path

    # Try to find in PATH
    iscc = shutil.which("ISCC")
    if iscc:
        return iscc

    return None


def create_placeholder_icon():
    """Create a simple placeholder icon if none exists."""
    icon_path = Path("assets/icon.ico")
    if icon_path.exists():
        print(f"✓ Icon found: {icon_path}")
        return True

    try:
        from PIL import Image, ImageDraw

        # Create a simple mouse icon
        size = 256
        img = Image.new('RGBA', (size, size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)

        # Green circle background
        draw.ellipse([10, 10, size-10, size-10], fill=(76, 175, 80, 255))

        # Mouse body (white)
        draw.ellipse([60, 80, 196, 220], fill=(255, 255, 255, 255))

        # Mouse ears
        draw.ellipse([45, 50, 100, 105], fill=(255, 255, 255, 255))
        draw.ellipse([156, 50, 211, 105], fill=(255, 255, 255, 255))

        # Center line
        draw.line([128, 90, 128, 160], fill=(76, 175, 80, 255), width=8)

        # Save as ICO with multiple sizes
        icon_path.parent.mkdir(parents=True, exist_ok=True)

        # Create multiple sizes for ICO
        sizes = [(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
        imgs = [img.resize(s, Image.Resampling.LANCZOS) for s in sizes]

        imgs[0].save(icon_path, format='ICO', sizes=[(s, s) for s in [16, 32, 48, 64, 128, 256]])
        print(f"✓ Created placeholder icon: {icon_path}")
        return True

    except ImportError:
        print("⚠ PIL not available, skipping icon creation")
        return False


def build_installer():
    """Build the installer with Inno Setup."""
    iscc = find_inno_setup()

    if not iscc:
        print("✗ Inno Setup not found!")
        print("  Download from: https://jrsoftware.org/isinfo.php")
        print("  Or run on Windows with Inno Setup installed")
        return False

    # Check if Nuitka build exists
    nuitka_output = Path("dist/automouse.__main__.dist")
    if not nuitka_output.exists():
        print("✗ Nuitka build not found!")
        print("  Run 'python build_windows.py' first")
        return False

    print(f"Using Inno Setup: {iscc}")

    # Create icon if needed
    create_placeholder_icon()

    # Run Inno Setup
    cmd = [iscc, "installer.iss"]
    print(f"\nRunning: {' '.join(cmd)}")

    result = subprocess.run(cmd)

    if result.returncode == 0:
        print("\n✓ Installer created successfully!")
        print("  Output: dist/AutoMouse-1.0.0-Setup.exe")
        return True
    else:
        print(f"\n✗ Installer build failed with code {result.returncode}")
        return False


if __name__ == "__main__":
    if not build_installer():
        sys.exit(1)
