from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, field
from typing import List


@dataclass(frozen=True)
class SystemAudioDevice:
    kind: str  # "dshow" | "wasapi"
    name: str
    label: str


@dataclass(frozen=True)
class DeviceLists:
    video: List[str]
    audio: List[str]
    system_audio: List[SystemAudioDevice] = field(default_factory=list)


def list_dshow_devices(ffmpeg_path: str) -> DeviceLists:
    """
    Lists DirectShow devices on Windows via FFmpeg.

    FFmpeg prints the device list in stderr, and the format can vary by build:
    - Old style: has "DirectShow audio devices" headers
    - New style: each device line ends with "(audio)" or "(video)"
    """
    cmd = [ffmpeg_path, "-hide_banner", "-list_devices", "true", "-f", "dshow", "-i", "dummy"]
    result = subprocess.run(cmd, capture_output=True, text=True)

    text = (result.stderr or "") + "\n" + (result.stdout or "")

    # If dshow isn't supported, FFmpeg usually says so.
    if "Unknown input format" in text or "unknown format" in text.lower():
        raise RuntimeError("FFmpeg does not support DirectShow (dshow) on this build.\n\n" + text)

    video, audio = _parse_dshow_device_list(text)
    system_audio = _build_system_audio_devices(ffmpeg_path, audio)
    return DeviceLists(video=video, audio=audio, system_audio=system_audio)


def supports_wasapi_loopback(ffmpeg_path: str) -> bool:
    return _ffmpeg_supports_input_format(ffmpeg_path, "wasapi")


def pick_default_mic(audio_devices: List[str]) -> str | None:
    if not audio_devices:
        return None

    for d in audio_devices:
        lower = d.lower()
        if "microphone" in lower or lower.startswith("mic ") or " mic" in lower:
            return d

    # Avoid selecting known loopback/system-output sources as microphone default.
    for d in audio_devices:
        if not _looks_like_system_audio_source(d):
            return d

    return audio_devices[0]


def pick_default_webcam(video_devices: List[str]) -> str | None:
    if not video_devices:
        return None

    keywords = ("webcam", "camera", "integrated", "facetime", "front", "rear")
    for device in video_devices:
        lower = device.lower()
        if any(keyword in lower for keyword in keywords):
            return device

    return video_devices[0]


def pick_default_system_audio(devices: List[SystemAudioDevice]) -> SystemAudioDevice | None:
    if not devices:
        return None

    for device in devices:
        if device.kind == "wasapi" and device.name.strip().lower() == "default":
            return device

    # Prefer explicit loopback-style DirectShow sources.
    keywords = ("stereo mix", "what u hear", "loopback", "wave out", "speaker", "headphone")
    for device in devices:
        lower = device.name.lower()
        if any(keyword in lower for keyword in keywords):
            return device

    return devices[0]


def _build_system_audio_devices(ffmpeg_path: str, dshow_audio_devices: List[str]) -> List[SystemAudioDevice]:
    devices: List[SystemAudioDevice] = []

    if _ffmpeg_supports_input_format(ffmpeg_path, "wasapi"):
        devices.append(
            SystemAudioDevice(
                kind="wasapi",
                name="default",
                label="Default Output (WASAPI Loopback)",
            )
        )
        for name in _list_wasapi_devices(ffmpeg_path):
            if _looks_like_mic_source(name):
                continue
            devices.append(
                SystemAudioDevice(
                    kind="wasapi",
                    name=name,
                    label=f"{name} (WASAPI Loopback)",
                )
            )

    seen = {f"{d.kind}:{d.name.lower()}" for d in devices}
    for name in _dshow_system_audio_candidates(dshow_audio_devices):
        key = f"dshow:{name.lower()}"
        if key in seen:
            continue
        devices.append(
            SystemAudioDevice(
                kind="dshow",
                name=name,
                label=f"{name} (DirectShow)",
            )
        )
        seen.add(key)

    return devices


def _ffmpeg_supports_input_format(ffmpeg_path: str, format_name: str) -> bool:
    try:
        result = subprocess.run(
            [ffmpeg_path, "-hide_banner", "-devices"],
            capture_output=True,
            text=True,
            timeout=8,
        )
    except Exception:
        return False

    text = (result.stdout or "") + "\n" + (result.stderr or "")
    pattern = re.compile(
        rf"^\s*D(?:[\.E]|\s)\s+{re.escape(format_name)}\b",
        re.IGNORECASE | re.MULTILINE,
    )
    return bool(pattern.search(text))


def _list_wasapi_devices(ffmpeg_path: str) -> List[str]:
    cmd = [ffmpeg_path, "-hide_banner", "-list_devices", "true", "-f", "wasapi", "-i", "dummy"]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=8)
    except Exception:
        return []

    text = (result.stderr or "") + "\n" + (result.stdout or "")
    devices: List[str] = []
    for line in text.splitlines():
        m = re.search(r'"([^"]+)"', line)
        if not m:
            continue
        name = m.group(1).strip()
        if not name:
            continue
        if name not in devices:
            devices.append(name)
    return devices


def _looks_like_system_audio_source(device_name: str) -> bool:
    lower = device_name.lower()
    system_keywords = (
        "stereo mix",
        "what u hear",
        "wave out",
        "loopback",
        "speaker",
        "speakers",
        "headphone",
        "line out",
        "digital output",
    )
    return any(keyword in lower for keyword in system_keywords)


def _looks_like_mic_source(device_name: str) -> bool:
    lower = device_name.lower()
    mic_keywords = ("microphone", "mic ", "micarray", "mic array", "line in", "line-in")
    return any(keyword in lower for keyword in mic_keywords)


def _dshow_system_audio_candidates(audio_devices: List[str]) -> List[str]:
    primary: List[str] = []
    secondary: List[str] = []
    tertiary: List[str] = []
    for name in audio_devices:
        if _looks_like_mic_source(name):
            continue
        if _looks_like_system_audio_source(name):
            primary.append(name)
        elif "output" in name.lower() or "render" in name.lower():
            secondary.append(name)
        else:
            tertiary.append(name)

    if primary:
        return list(dict.fromkeys(primary))
    if secondary:
        return list(dict.fromkeys(secondary))
    if tertiary:
        return list(dict.fromkeys(tertiary))
    return []


def _parse_dshow_device_list(text: str) -> tuple[List[str], List[str]]:
    """
    Parses device names from FFmpeg output.

    Works with BOTH styles:
    - "Microphone ..."(audio)
    - Header-based lists
    """
    video_devices: List[str] = []
    audio_devices: List[str] = []

    mode: str | None = None  # None / "video" / "audio"

    for line in text.splitlines():
        lower = line.lower()

        # Old style headers
        if "directshow video devices" in lower:
            mode = "video"
            continue
        if "directshow audio devices" in lower:
            mode = "audio"
            continue

        # New style: device line contains "(video)" or "(audio)"
        line_type = None
        if "(video)" in lower:
            line_type = "video"
        elif "(audio)" in lower:
            line_type = "audio"

        # Extract quoted device name
        m = re.search(r'"([^"]+)"', line)
        if not m:
            continue

        name = m.group(1).strip()
        if not name:
            continue

        # Prefer new-style tagging when present; otherwise fall back to header mode
        effective_mode = line_type or mode

        if effective_mode == "video":
            if name not in video_devices:
                video_devices.append(name)
        elif effective_mode == "audio":
            if name not in audio_devices:
                audio_devices.append(name)

    return video_devices, audio_devices
