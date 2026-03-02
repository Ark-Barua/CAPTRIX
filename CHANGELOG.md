# Changelog

All notable changes to this project are documented in this file.

The format is based on Keep a Changelog and this project follows Semantic Versioning.

## [1.0.0] - 2026-03-03

### Added
- Automatic H.264 encoder selection with FFmpeg capability probing (`h264_nvenc`, `h264_qsv`, `h264_amf`) and CPU fallback (`libx264`).
- Quality profiles for recording: `Balanced`, `High Quality`, and `Small File`.
- GPU vendor-aware encoder prioritization with optional advisor hook (`app/core/encoder_ai_advisor.py`).
- Webcam overlay reliability fallback: if webcam startup fails, recording continues without webcam instead of hard-failing.
- Improved About section with runtime diagnostics report and copy-to-clipboard support.
- Modernized recording workspace UI with sectioned controls, library tabs, and clearer status signaling.
- Recovery workflow for unfinished recording sessions (recover/delete/later).

### Changed
- Encoder mode in UI is now auto-managed (`Auto (Best Available)`).
- System audio device diagnostics now include explicit WASAPI loopback support checks.

### Fixed
- Start-time FFmpeg failures caused by webcam demux I/O errors now trigger graceful fallback behavior.
- Filter graph ordering and startup handling improvements for mixed video/audio capture paths.

