# Building AutoMouse for Windows

This guide covers creating a distributable Windows installer for AutoMouse.

## Why Nuitka + Inno Setup?

Python executables often trigger antivirus false positives. We use:

- **Nuitka**: Compiles Python to C, then to native code. Lower false-positive rate than PyInstaller.
- **Inno Setup**: Creates a proper Windows installer, which looks more legitimate to AV software.

This combination minimizes (but doesn't eliminate) AV issues. For zero false positives, you'd need a code signing certificate (~$100-300/year).

## Prerequisites

### 1. Python Dependencies

```bash
pip install nuitka ordered-set zstandard
```

### 2. C Compiler (one of these)

**Option A: MinGW-w64 (Recommended, free)**
- Download from: https://www.mingw-w64.org/downloads/
- Or via MSYS2: https://www.msys2.org/
- Add to PATH after installing

**Option B: Visual Studio Build Tools**
- Download "Build Tools for Visual Studio" from: https://visualstudio.microsoft.com/downloads/
- Install "Desktop development with C++"

### 3. Inno Setup 6

- Download from: https://jrsoftware.org/isinfo.php
- Install to default location

## Building

### Step 1: Build the Executable

```bash
python build_windows.py
```

This creates a standalone build in `dist/automouse.__main__.dist/`

### Step 2: Test the Build

```bash
dist\automouse.__main__.dist\AutoMouse.exe
```

Make sure everything works before creating the installer.

### Step 3: Create the Installer

```bash
python build_installer.py
```

This creates `dist/AutoMouse-1.0.0-Setup.exe`

## Dealing with Antivirus Issues

### If Windows Defender Flags the Build

1. **Submit a false positive report**: https://www.microsoft.com/en-us/wdsi/filesubmission
2. The executable should be whitelisted within 24-48 hours
3. You'll need to do this for each new version

### For Other Antivirus Software

- **Avast/AVG**: https://www.avast.com/false-positive-file-form.php
- **Bitdefender**: https://www.bitdefender.com/consumer/support/answer/29358/
- **Norton**: https://submit.norton.com/
- **Kaspersky**: https://opentip.kaspersky.com/

### Best Practices to Minimize False Positives

1. Don't use `--onefile` mode (already configured)
2. Include proper Windows metadata (company name, version, description)
3. Use Inno Setup for the installer (not self-extracting archives)
4. Consider code signing for production releases

## Code Signing (Optional but Recommended)

For production releases, a code signing certificate eliminates most AV issues:

### Providers (prices vary)

- **Sectigo/Comodo**: ~$100-200/year (standard), ~$300-400/year (EV)
- **DigiCert**: ~$300-500/year
- **SSL.com**: ~$100-200/year

### EV vs Standard Certificates

- **Standard**: Builds reputation over time, some initial flags possible
- **EV (Extended Validation)**: Trusted immediately, stored on hardware token

### Signing the Installer

1. Uncomment the `SignTool` line in `installer.iss`
2. Configure your signing tool path
3. Rebuild the installer

## Troubleshooting

### "Nuitka not found"
```bash
pip install nuitka ordered-set zstandard
```

### "No C compiler found"
Install MinGW-w64 or Visual Studio Build Tools (see Prerequisites)

### "Inno Setup not found"
Install Inno Setup 6 from https://jrsoftware.org/isinfo.php

### Build succeeds but EXE crashes
- Check that all dependencies are included in `build_windows.py`
- Look for missing DLLs in the error message
- Try running from command line to see error output

## File Structure After Build

```
dist/
├── automouse.__main__.dist/    # Nuitka output
│   ├── AutoMouse.exe           # Main executable
│   ├── python3X.dll            # Python runtime
│   ├── *.pyd                   # Compiled Python modules
│   └── ...                     # Other dependencies
└── AutoMouse-1.0.0-Setup.exe   # Final installer
```
