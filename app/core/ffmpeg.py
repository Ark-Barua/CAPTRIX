from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
import shutil


@dataclass(frozen=True)
class FFmpegStatus:
    found: bool
    path: str | None
    version: str | None
    error: str | None


def detect_ffmpeg() -> FFmpegStatus:
    """
    Prefer a project-local FFmpeg (tools/ffmpeg/bin/ffmpeg.exe) so dev is stable.
    Fallback to system PATH if not found.
    """
    project_root = Path(__file__).resolve().parents[2]  # .../CAPTRIX/app/core -> CAPTRIX
    local_ffmpeg = project_root / "tools" / "ffmpeg" / "bin" / "ffmpeg.exe"

    if local_ffmpeg.exists():
        return _probe_ffmpeg(str(local_ffmpeg))

    ffmpeg_path = shutil.which("ffmpeg")
    if not ffmpeg_path:
        return FFmpegStatus(
            found=False,
            path=None,
            version=None,
            error="FFmpeg not found. Put ffmpeg.exe in tools/ffmpeg/bin OR install FFmpeg and restart terminal.",
        )

    return _probe_ffmpeg(ffmpeg_path)


def _probe_ffmpeg(ffmpeg_path: str) -> FFmpegStatus:
    try:
        result = subprocess.run(
            [ffmpeg_path, "-version"],
            capture_output=True,
            text=True,
            check=False,
        )

        if result.returncode != 0:
            return FFmpegStatus(
                found=False,
                path=ffmpeg_path,
                version=None,
                error=result.stderr.strip() or "FFmpeg returned a non-zero exit code.",
            )

        first_line = result.stdout.splitlines()[0].strip()
        return FFmpegStatus(found=True, path=ffmpeg_path, version=first_line, error=None)

    except Exception as e:
        return FFmpegStatus(found=False, path=ffmpeg_path, version=None, error=str(e))