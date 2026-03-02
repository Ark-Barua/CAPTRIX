# CAPTRIX

[![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![Platform](https://img.shields.io/badge/Platform-Windows%2010%2F11-0078D6?logo=windows&logoColor=white)](#platform-support)
[![UI](https://img.shields.io/badge/UI-PySide6-41CD52?logo=qt&logoColor=white)](https://pypi.org/project/PySide6/)
[![FFmpeg](https://img.shields.io/badge/FFmpeg-Required-007808?logo=ffmpeg&logoColor=white)](https://ffmpeg.org/)
[![License](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

CAPTRIX is a Windows desktop screen recorder built with PySide6 and FFmpeg.  
It supports region/fullscreen/window capture, webcam picture-in-picture, mixed audio capture, crash-safe recording, and an in-app recording library.

## Latest Updates (March 2026)

- Encoder mode is now fully automatic in UI (`Auto (Best Available)`), with quality presets:
  - `Balanced`
  - `High Quality`
  - `Small File`
- Added robust FFmpeg encoder capability detection (`h264_nvenc`, `h264_qsv`, `h264_amf`)
- Added GPU vendor-aware auto encoder priority (NVIDIA/AMD/Intel) with safe CPU fallback (`libx264`)
- Added webcam startup fault isolation:
  - If webcam overlay cannot start, recording continues automatically without webcam
  - User receives a clear warning, instead of full recording start failure
- Added improved About panel/runtime report:
  - Detailed runtime diagnostics dialog
  - One-click copy of runtime report for troubleshooting
- Preserved full capture pipeline compatibility:
  - Region selection
  - Webcam overlay (PiP)
  - Mic + system audio mix
  - Temp MKV recording and MP4 finalize/remux

## Feature Overview

- Modern desktop UI (PySide6, custom icon set)
- Recording modes:
  - Rectangle area
  - Fullscreen
  - Specific window
  - Device recording
  - Game recording (60 fps profile)
  - Audio only
- Webcam overlay (PiP):
  - Enable/disable
  - Device selection
  - Size slider
  - Position presets (TL/TR/BL/BR)
  - Pre-configuration available even when overlay is currently off
- Audio controls:
  - Microphone capture
  - Optional system audio capture (WASAPI loopback / DirectShow fallback)
  - Mic and system volume sliders
  - Audio mixing in FFmpeg
- Auto encoder engine:
  - Auto-detects available H.264 hardware encoders in FFmpeg
  - Picks best available encoder by detected hardware priority
  - Falls back to CPU x264 if hardware encoder startup fails
- Built-in screenshot capture from visual modes
- Sync test clip generation (flash + beep)
- Crash-safe recording lifecycle:
  - Capture to MKV in temp directory
  - Remux to MP4 on stop
  - Startup recovery for unfinished sessions
- In-app recording library:
  - Videos / Images / Audios tabs
  - Metadata table (filename, duration, size, created time)
  - Search filter
  - Open / Rename / Delete / Reveal / Open Folder actions
- Professional About section with runtime report and copy-to-clipboard diagnostics

## Platform Support

- Primary target: **Windows 10/11**
- Capture pipeline uses FFmpeg inputs such as `gdigrab`, `dshow`, and `wasapi` (Windows-specific in this app)

## Requirements

- Python 3.10+ (3.11+ recommended)
- FFmpeg with required components:
  - `ffmpeg.exe` (required)
  - `ffprobe.exe` (recommended for duration metadata in library)
  - Input formats used by CAPTRIX: `gdigrab`, `dshow`, `wasapi`
- Python dependency:
  - `PySide6>=6.10.2`

## FFmpeg Setup

CAPTRIX checks FFmpeg in this order:

1. Local bundled path:
   - `tools/ffmpeg/bin/ffmpeg.exe`
2. System PATH:
   - `ffmpeg` from your environment

If FFmpeg is not found, CAPTRIX shows setup warnings and disables recording actions.

### Encoder Strategy (Current Behavior)

- Encoder selection is auto-managed by CAPTRIX.
- Manual forcing of CPU/NVIDIA/Intel/AMD is no longer exposed in the UI.
- CAPTRIX resolves the effective encoder at start time using:
  - FFmpeg encoder support probe (`-encoders`)
  - Detected GPU vendor priority on the host
  - Optional advisor hook (`app/core/encoder_ai_advisor.py`)
- If the chosen hardware encoder fails at startup, CAPTRIX retries automatically with CPU x264.

### Quality Presets

- `Balanced`
  - CPU: `libx264 -preset veryfast -crf 23`
  - NVIDIA: `h264_nvenc -preset p4 -cq 23`
  - Intel: `h264_qsv -global_quality 23`
  - AMD: `h264_amf -quality balanced`
- `High Quality`
  - CPU: `libx264 -preset faster -crf 20`
  - NVIDIA: `h264_nvenc -preset p5 -cq 19`
  - Intel: `h264_qsv -global_quality 19`
  - AMD: `h264_amf -quality quality`
- `Small File`
  - CPU: `libx264 -preset veryfast -crf 28`
  - NVIDIA: `h264_nvenc -preset p3 -cq 28`
  - Intel: `h264_qsv -global_quality 28`
  - AMD: `h264_amf -quality speed`

### Optional Encoder Advisor Hook

You can customize auto encoder selection using:

- `app/core/encoder_ai_advisor.py`
- Function signature: `recommend_encoder(context: dict[str, object]) -> str | None`

This hook is loaded dynamically when present and can return one of:

- `nvidia`
- `intel`
- `amd`

## Installation

```powershell
git clone <your-repo-url> CAPTRIX
cd CAPTRIX
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## Run

```powershell
python main.py
```

## Build EXE (PyInstaller)

Build a single-file Windows executable:

```powershell
pyinstaller --noconsole --onefile --name CAPTRIX --icon assets\captrix.ico main.py
```

Build output:

- `dist\CAPTRIX.exe`

Optional clean rebuild:

```powershell
pyinstaller --clean --noconfirm --noconsole --onefile --name CAPTRIX --icon assets\captrix.ico main.py
```

## Data and File Locations

CAPTRIX stores runtime data in:

- `C:\Users\<you>\.captrix\settings`
- `C:\Users\<you>\.captrix\temp`
- `C:\Users\<you>\.captrix\recordings` (default; configurable in UI)

### Recording Lifecycle

During recording:

- Video is written to:  
  `.captrix/temp/<session_id>.mkv`
- Session manifest is written to:  
  `.captrix/temp/<session_id>.json`
- Session lock file is written to:  
  `.captrix/temp/<session_id>.lock`

On stop:

- CAPTRIX remuxes MKV to MP4 in the recordings folder
- Session manifest status is updated to `finalized`
- Old finalized temp artifacts are cleaned automatically

## Crash Recovery

On startup, CAPTRIX scans `.captrix/temp` for unfinished sessions and offers:

- **Recover All**: remuxes unfinished MKV files to MP4
- **Delete All**: removes unfinished temp sessions
- **Later**: keeps sessions untouched for manual recovery later

This protects recordings from app/system interruptions.

## In-App Recording Library

Each library tab shows files from the recordings folder:

- **Videos**
- **Images**
- **Audios**

Available operations:

- Refresh
- Search by filename
- Open selected file
- Rename selected file
- Delete selected file
- Reveal selected file in Explorer
- Open recordings folder

## Usage Notes

- Webcam preview is shown when overlay is enabled and recording is idle.
- During recording, live webcam preview is hidden to avoid capturing it.
- Webcam device/size/position can be configured before enabling overlay.
- If webcam overlay fails to initialize, CAPTRIX auto-disables webcam for that recording and continues.
- If system audio source matches microphone source, CAPTRIX blocks start to prevent obvious double-capture/echo.
- For long-session stability, CAPTRIX uses timestamp normalization and audio resampling filters in FFmpeg.
- About panel provides a detailed runtime report that can be copied for support/debugging.

## Troubleshooting

### FFmpeg not detected

- Put `ffmpeg.exe` in `tools/ffmpeg/bin/`
- Or install FFmpeg globally and ensure `ffmpeg -version` works in terminal

### No webcam/microphone/system audio devices

- Ensure the device is connected and not exclusively locked by another app
- Restart CAPTRIX after connecting devices

### Webcam overlay fails to start

- Close other apps using the webcam (camera apps, browser tabs, conferencing apps)
- Try another webcam format/device in system settings
- CAPTRIX now automatically retries recording without webcam overlay when webcam startup fails

### Recording stop/finalize fails

- Check whether temp MKV exists under `.captrix/temp`
- Restart app and use startup recovery
- Verify enough free disk space in temp and recordings locations

### Library duration is `N/A`

- `ffprobe.exe` may be missing from FFmpeg install
- CAPTRIX can still record/play files; only duration probing is affected

### PyInstaller icon format error

If you see an error like:

- `ValueError: ... icon image ... is not in the correct format`

Then `assets\captrix.ico` is likely not a real ICO container (for example, a PNG file renamed to `.ico`).

Fix options:

- Replace it with a valid `.ico` file
- Or convert it in-place using PySide6:

```powershell
python -c "from PySide6.QtGui import QImage; p='assets/captrix.ico'; img=QImage(p); print('loaded=', not img.isNull(), 'saved=', img.save(p, 'ICO'))"
```

## Project Structure

```text
CAPTRIX/
  main.py
  requirements.txt
  app/
    core/
      ffmpeg.py
      paths.py
      recorder.py
      win_devices.py
      win_windows.py
    ui/
      main_window.py
      region_selector.py
      icon_factory.py
```

## License

This project is licensed under the **MIT License**.  
See [LICENSE](LICENSE) for details.
