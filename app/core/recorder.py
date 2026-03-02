from __future__ import annotations

import ctypes
import importlib.util
import json
import os
import signal
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import time
import uuid
from typing import TextIO


@dataclass(frozen=True)
class CaptureRegion:
    x: int
    y: int
    width: int
    height: int


@dataclass(frozen=True)
class WebcamOverlay:
    device_name: str
    size_percent: int = 24
    position: str = "bottom_right"
    margin_px: int = 24


@dataclass(frozen=True)
class RecordingResult:
    mkv_path: Path
    mp4_path: Path


@dataclass(frozen=True)
class RecoverySession:
    session_id: str
    mkv_path: Path
    mp4_path: Path
    manifest_path: Path | None
    start_time: str | None
    status: str
    size_bytes: int


@dataclass(frozen=True)
class RecordingLibraryItem:
    path: Path
    filename: str
    duration_sec: float | None
    size_bytes: int
    created_at: datetime


@dataclass(frozen=True)
class H264EncoderSupport:
    nvidia: bool
    intel: bool
    amd: bool
    error: str | None = None


@dataclass(frozen=True)
class VideoEncodingPlan:
    requested_encoder: str
    quality_preset: str
    selected_encoder: str
    selected_ffmpeg_encoder: str
    primary_args: tuple[str, ...]
    cpu_fallback_args: tuple[str, ...] | None
    selection_note: str | None
    support: H264EncoderSupport


class WebcamInputError(RuntimeError):
    """Raised when FFmpeg cannot read frames from the selected webcam."""


class RecorderController:
    def __init__(self, ffmpeg_path: str, recordings_dir: Path, temp_dir: Path) -> None:
        self.ffmpeg_path = ffmpeg_path
        self.recordings_dir = recordings_dir
        self.temp_dir = temp_dir
        self.recordings_dir.mkdir(parents=True, exist_ok=True)
        self.temp_dir.mkdir(parents=True, exist_ok=True)

        self._proc: subprocess.Popen[str] | None = None
        self._current_mkv: Path | None = None
        self._current_mp4: Path | None = None
        self._ffmpeg_log_path: Path | None = None
        self._ffmpeg_log_file: TextIO | None = None
        self._current_session_id: str | None = None
        self._current_manifest_path: Path | None = None
        self._current_lock_path: Path | None = None
        self._webcam_args_cache: dict[str, list[str]] = {}
        self._ffprobe_path_cache: str | None = None
        self._h264_encoder_support_cache: H264EncoderSupport | None = None
        self._gpu_vendor_priority_cache: list[str] | None = None

    def is_recording(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def start_recording_windows_fullscreen_mic(
        self,
        mic_name: str,
        region: CaptureRegion | None = None,
        region_mode: str = "crop",
        webcam_overlay: WebcamOverlay | None = None,
        system_audio_device: str | None = None,
        system_audio_kind: str | None = None,
        mic_volume_percent: int = 100,
        system_audio_volume_percent: int = 100,
        encoder_preference: str = "auto",
        quality_preset: str = "balanced",
    ) -> None:
        encoding_plan = self.resolve_video_encoding_plan(
            encoder_preference=encoder_preference,
            quality_preset=quality_preset,
            fps=30,
        )
        screen_input_args, screen_filter = self._build_screen_input_with_optional_filter(
            region=region,
            region_mode=region_mode,
            for_complex_filter=True,
        )
        if webcam_overlay is None:
            capture_mode = "region" if region is not None else "fullscreen"
            region_info = None
            if region is not None:
                region_info = {
                    "x": int(region.x),
                    "y": int(region.y),
                    "width": int(region.width),
                    "height": int(region.height),
                    "mode": region_mode,
                }
            self._start_video_capture_with_optional_webcam_and_mix(
                video_input_args=screen_input_args,
                mic_name=mic_name,
                webcam_overlay=None,
                base_video_filter=screen_filter,
                system_audio_device=system_audio_device,
                system_audio_kind=system_audio_kind,
                mic_volume_percent=mic_volume_percent,
                system_volume_percent=system_audio_volume_percent,
                video_encoding_plan=encoding_plan,
                capture_context={
                    "mode": capture_mode,
                    "source": "desktop",
                    "region": region_info,
                    "region_mode": region_mode,
                },
            )
            return

        self._start_video_capture_with_optional_webcam_and_mix(
            video_input_args=screen_input_args,
            mic_name=mic_name,
            webcam_overlay=webcam_overlay,
            base_video_filter=screen_filter,
            system_audio_device=system_audio_device,
            system_audio_kind=system_audio_kind,
            mic_volume_percent=mic_volume_percent,
            system_volume_percent=system_audio_volume_percent,
            video_encoding_plan=encoding_plan,
            capture_context={
                "mode": "region" if region is not None else "fullscreen",
                "source": "desktop",
                "region": (
                    {
                        "x": int(region.x),
                        "y": int(region.y),
                        "width": int(region.width),
                        "height": int(region.height),
                        "mode": region_mode,
                    }
                    if region is not None
                    else None
                ),
                "region_mode": region_mode,
            },
        )

    def start_recording_window_mic(
        self,
        mic_name: str,
        window_title: str,
        webcam_overlay: WebcamOverlay | None = None,
        system_audio_device: str | None = None,
        system_audio_kind: str | None = None,
        mic_volume_percent: int = 100,
        system_audio_volume_percent: int = 100,
        encoder_preference: str = "auto",
        quality_preset: str = "balanced",
    ) -> None:
        if not window_title.strip():
            raise RuntimeError("Window title is required for window recording.")

        encoding_plan = self.resolve_video_encoding_plan(
            encoder_preference=encoder_preference,
            quality_preset=quality_preset,
            fps=30,
        )
        self._start_video_capture_with_optional_webcam_and_mix(
            video_input_args=self._window_capture_input_args(window_title=window_title, fps=30, hide_mouse=False),
            mic_name=mic_name,
            webcam_overlay=webcam_overlay,
            base_video_filter=None,
            system_audio_device=system_audio_device,
            system_audio_kind=system_audio_kind,
            mic_volume_percent=mic_volume_percent,
            system_volume_percent=system_audio_volume_percent,
            video_encoding_plan=encoding_plan,
            capture_context={
                "mode": "window",
                "source": "window",
                "window_title": window_title,
                "fps": 30,
            },
        )

    def start_recording_game_window_mic(
        self,
        mic_name: str,
        window_title: str,
        webcam_overlay: WebcamOverlay | None = None,
        system_audio_device: str | None = None,
        system_audio_kind: str | None = None,
        mic_volume_percent: int = 100,
        system_audio_volume_percent: int = 100,
        encoder_preference: str = "auto",
        quality_preset: str = "balanced",
    ) -> None:
        if not window_title.strip():
            raise RuntimeError("Game window title is required for game recording.")

        encoding_plan = self.resolve_video_encoding_plan(
            encoder_preference=encoder_preference,
            quality_preset=quality_preset,
            fps=60,
        )
        self._start_video_capture_with_optional_webcam_and_mix(
            video_input_args=self._window_capture_input_args(window_title=window_title, fps=60, hide_mouse=True),
            mic_name=mic_name,
            webcam_overlay=webcam_overlay,
            base_video_filter=None,
            system_audio_device=system_audio_device,
            system_audio_kind=system_audio_kind,
            mic_volume_percent=mic_volume_percent,
            system_volume_percent=system_audio_volume_percent,
            video_encoding_plan=encoding_plan,
            capture_context={
                "mode": "game",
                "source": "window",
                "window_title": window_title,
                "fps": 60,
            },
        )

    def _start_video_capture_with_optional_webcam_and_mix(
        self,
        video_input_args: list[str],
        mic_name: str,
        webcam_overlay: WebcamOverlay | None = None,
        base_video_filter: str | None = None,
        system_audio_device: str | None = None,
        system_audio_kind: str | None = None,
        mic_volume_percent: int = 100,
        system_volume_percent: int = 100,
        video_encoding_plan: VideoEncodingPlan | None = None,
        capture_context: dict[str, object] | None = None,
    ) -> None:
        encoding_plan = video_encoding_plan or self.resolve_video_encoding_plan(
            encoder_preference="auto",
            quality_preset="balanced",
            fps=30,
        )
        cmd = [self.ffmpeg_path, "-y"]
        cmd += self._input_timestamp_args()
        cmd += video_input_args

        next_index = 1
        if webcam_overlay is not None:
            cmd += self._webcam_input_args(webcam_overlay.device_name)
            next_index = 2

        cmd += self._audio_input_args(mic_name)
        mic_input_index = next_index
        next_index += 1

        system_input_index: int | None = None
        if system_audio_device and system_audio_device.strip():
            backend = (system_audio_kind or "dshow").lower().strip()
            # Avoid obvious double-capture/echo case where system and mic sources are identical.
            if backend == "dshow" and system_audio_device.strip().lower() == mic_name.strip().lower():
                raise RuntimeError(
                    "System audio source matches the microphone source. "
                    "Choose a loopback/output source for system audio."
                )
            if backend == "dshow" and "microphone" in system_audio_device.strip().lower():
                raise RuntimeError(
                    "Selected system audio source appears to be a microphone input. "
                    "Choose a loopback/output source to avoid echo and double capture."
                )
            cmd += self._system_audio_input_args(system_audio_device, backend=backend)
            system_input_index = next_index

        filter_parts: list[str] = []
        if webcam_overlay is not None:
            filter_parts.append(self._webcam_overlay_filter_graph(webcam_overlay, base_filter=base_video_filter))
            video_map = "[vout]"
        else:
            # Normalize base video timestamps in all no-webcam capture paths.
            if base_video_filter:
                filter_parts.append(f"[0:v]setpts=PTS-STARTPTS,{base_video_filter}[vout]")
            else:
                filter_parts.append("[0:v]setpts=PTS-STARTPTS[vout]")
            video_map = "[vout]"

        filter_parts.append(
            self._audio_mix_filter_graph(
                mic_input_index=mic_input_index,
                system_input_index=system_input_index,
                mic_volume_percent=mic_volume_percent,
                system_volume_percent=system_volume_percent,
            )
        )
        cmd += ["-filter_complex", ";".join(filter_parts)]
        cmd += ["-map", video_map, "-map", "[aout]"]
        session_info_base = {
            "capture": capture_context or {"mode": "unknown"},
            "webcam": (
                {
                    "enabled": True,
                    "device": webcam_overlay.device_name,
                    "size_percent": int(webcam_overlay.size_percent),
                    "position": webcam_overlay.position,
                    "margin_px": int(webcam_overlay.margin_px),
                }
                if webcam_overlay is not None
                else {"enabled": False}
            ),
            "audio": {
                "mic": mic_name,
                "mic_volume_percent": int(mic_volume_percent),
                "system_audio_enabled": system_input_index is not None,
                "system_audio_device": system_audio_device if system_input_index is not None else None,
                "system_audio_kind": (system_audio_kind or "dshow") if system_input_index is not None else None,
                "system_audio_volume_percent": int(system_volume_percent),
            },
        }
        try:
            self._start_video_command_with_cpu_fallback(
                cmd_without_output=cmd,
                session_info_base=session_info_base,
                encoding_plan=encoding_plan,
                include_audio=True,
            )
        except Exception as exc:
            if webcam_overlay is not None and self._looks_like_webcam_input_error(
                error_text=str(exc),
                device_name=webcam_overlay.device_name,
            ):
                raise WebcamInputError(
                    "Webcam overlay could not start because FFmpeg could not read webcam frames.\n"
                    f"Device: {webcam_overlay.device_name}\n{exc}"
                ) from exc
            raise

    def start_recording_device(
        self,
        video_device: str,
        audio_device: str | None = None,
        encoder_preference: str = "auto",
        quality_preset: str = "balanced",
    ) -> None:
        if not video_device.strip():
            raise RuntimeError("Video capture device is required.")

        encoding_plan = self.resolve_video_encoding_plan(
            encoder_preference=encoder_preference,
            quality_preset=quality_preset,
            fps=30,
        )
        input_spec = f"video={video_device}"
        if audio_device and audio_device.strip():
            input_spec = f"{input_spec}:audio={audio_device}"

        cmd = [
            self.ffmpeg_path,
            "-y",
            *self._input_timestamp_args(),
            "-f",
            "dshow",
            "-i",
            input_spec,
        ]
        if audio_device and audio_device.strip():
            cmd += self._av_sync_args()
        self._start_video_command_with_cpu_fallback(
            cmd_without_output=cmd,
            session_info_base={
                "capture": {
                    "mode": "device",
                    "source": "device",
                    "video_device": video_device,
                    "audio_device": audio_device or None,
                },
                "webcam": {"enabled": False},
                "audio": {
                    "mic": audio_device or None,
                    "mic_volume_percent": 100,
                    "system_audio_enabled": False,
                    "system_audio_device": None,
                    "system_audio_kind": None,
                    "system_audio_volume_percent": 100,
                },
            },
            encoding_plan=encoding_plan,
            include_audio=bool(audio_device and audio_device.strip()),
        )

    def start_recording_audio_only(self, audio_device: str) -> None:
        if not audio_device.strip():
            raise RuntimeError("Audio source is required for audio-only recording.")

        cmd = [
            self.ffmpeg_path,
            "-y",
            *self._input_timestamp_args(),
            "-f",
            "dshow",
            "-i",
            f"audio={audio_device}",
        ]
        cmd += self._av_sync_args()
        cmd += self._audio_encode_args()
        self._start_command(
            cmd,
            session_info={
                "capture": {
                    "mode": "audio",
                    "source": "audio_only",
                },
                "webcam": {"enabled": False},
                "audio": {
                    "mic": audio_device,
                    "mic_volume_percent": 100,
                    "system_audio_enabled": False,
                    "system_audio_device": None,
                    "system_audio_kind": None,
                    "system_audio_volume_percent": 100,
                },
            },
        )

    def take_screenshot_fullscreen(
        self,
        region: CaptureRegion | None = None,
        region_mode: str = "crop",
    ) -> Path:
        cmd = [self.ffmpeg_path, "-y"]
        cmd += self._build_screen_input_args(region=region, region_mode=region_mode)
        output_path = self._prepare_screenshot_path()
        self._run_single_frame_capture(cmd, output_path)
        return output_path

    def take_screenshot_window(self, window_title: str) -> Path:
        if not window_title.strip():
            raise RuntimeError("Window title is required for screenshot capture.")

        cmd = [
            self.ffmpeg_path,
            "-y",
            "-f",
            "gdigrab",
            "-framerate",
            "30",
            "-i",
            f"title={window_title}",
        ]
        output_path = self._prepare_screenshot_path()
        self._run_single_frame_capture(cmd, output_path)
        return output_path

    def take_screenshot_device(self, video_device: str) -> Path:
        if not video_device.strip():
            raise RuntimeError("Video capture device is required for screenshot capture.")

        cmd = [
            self.ffmpeg_path,
            "-y",
            "-f",
            "dshow",
            "-i",
            f"video={video_device}",
        ]
        output_path = self._prepare_screenshot_path()
        self._run_single_frame_capture(cmd, output_path, timeout_sec=25)
        return output_path

    def generate_sync_test_clip(self, duration_sec: int = 8, fps: int = 30) -> Path:
        if self.is_recording():
            raise RuntimeError("Stop current recording before generating a sync test clip.")

        duration = max(3, min(60, int(duration_sec)))
        target_fps = max(15, min(60, int(fps)))
        sample_rate = 48000

        self.recordings_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        out_path = self.recordings_dir / f"captrix_sync_test_{stamp}.mp4"

        video_src = f"color=c=black:s=1280x720:r={target_fps}:d={duration}"
        audio_src = (
            "aevalsrc="
            "exprs='if(lt(mod(t,1),0.08),0.9*sin(2*PI*1000*t),0)'"
            f":s={sample_rate}:d={duration}"
        )
        flash_filter = "drawbox=x=0:y=0:w=iw:h=ih:color=white:t=fill:enable='lt(mod(t,1),0.08)'"

        cmd = [
            self.ffmpeg_path,
            "-y",
            "-f",
            "lavfi",
            "-i",
            video_src,
            "-f",
            "lavfi",
            "-i",
            audio_src,
            "-filter_complex",
            f"[0:v]{flash_filter},setpts=PTS-STARTPTS[vout];"
            "[1:a]aresample=async=1:first_pts=0[aout]",
            "-map",
            "[vout]",
            "-map",
            "[aout]",
            *self._video_encode_args(crf="18", fps=target_fps),
            *self._audio_encode_args(),
            str(out_path),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0 and out_path.exists() and out_path.stat().st_size > 0:
            return out_path

        try:
            if out_path.exists():
                out_path.unlink()
        except Exception:
            pass

        stderr = (result.stderr or "").strip()
        if not stderr:
            stderr = "Failed to generate sync test clip."
        raise RuntimeError(stderr)

    def get_h264_encoder_support(self, refresh: bool = False) -> H264EncoderSupport:
        if self._h264_encoder_support_cache is not None and not refresh:
            return self._h264_encoder_support_cache

        support = self._probe_h264_encoder_support()
        self._h264_encoder_support_cache = support
        return support

    def resolve_video_encoding_plan(
        self,
        encoder_preference: str = "auto",
        quality_preset: str = "balanced",
        fps: int = 30,
    ) -> VideoEncodingPlan:
        requested = self._normalize_encoder_preference(encoder_preference)
        quality = self._normalize_quality_preset(quality_preset)
        support = self.get_h264_encoder_support(refresh=False)

        selected = "cpu"
        selection_note: str | None = None

        if requested == "auto":
            auto_candidates = self._auto_encoder_candidates(
                support=support,
                quality_preset=quality,
                fps=fps,
            )
            for candidate in auto_candidates:
                if self._is_h264_encoder_supported(candidate, support):
                    selected = candidate
                    selection_note = (
                        f"Auto-selected {self._encoder_display_name(candidate)} based on "
                        "detected hardware and encoder availability."
                    )
                    break
            else:
                selected = "cpu"
                selection_note = "No supported hardware H.264 encoder detected on this system. Using CPU x264."
        elif requested == "cpu":
            selected = "cpu"
        elif self._is_h264_encoder_supported(requested, support):
            selected = requested
        else:
            selected = "cpu"
            selection_note = (
                f"{self._encoder_display_name(requested)} encoder is unavailable in this FFmpeg build. "
                "Using CPU x264."
            )

        primary_args = tuple(
            self._video_encode_args_for_encoder(
                encoder=selected,
                quality_preset=quality,
                fps=fps,
            )
        )
        cpu_fallback_args = (
            tuple(
                self._video_encode_args_for_encoder(
                    encoder="cpu",
                    quality_preset=quality,
                    fps=fps,
                )
            )
            if selected != "cpu"
            else None
        )
        return VideoEncodingPlan(
            requested_encoder=requested,
            quality_preset=quality,
            selected_encoder=selected,
            selected_ffmpeg_encoder=self._ffmpeg_encoder_name(selected),
            primary_args=primary_args,
            cpu_fallback_args=cpu_fallback_args,
            selection_note=selection_note,
            support=support,
        )

    def _auto_encoder_candidates(self, support: H264EncoderSupport, quality_preset: str, fps: int) -> list[str]:
        # Base order by hardware detected on this machine.
        candidates = self._detected_gpu_vendor_priority(refresh=False)
        if not candidates:
            candidates = ["nvidia", "amd", "intel"]

        # Optional local AI advisor hook. If present and valid, it can override first choice.
        ai_choice = self._ai_advised_encoder_choice(
            gpu_priority=candidates,
            support=support,
            quality_preset=quality_preset,
            fps=fps,
        )
        if ai_choice and ai_choice in {"nvidia", "amd", "intel"}:
            ordered = [ai_choice]
            ordered.extend([c for c in candidates if c != ai_choice])
            return ordered
        return candidates

    def _detected_gpu_vendor_priority(self, refresh: bool = False) -> list[str]:
        if self._gpu_vendor_priority_cache is not None and not refresh:
            return [*self._gpu_vendor_priority_cache]

        detected = self._probe_gpu_vendor_priority()
        # Default order if hardware vendor probing fails.
        if not detected:
            detected = ["nvidia", "amd", "intel"]
        self._gpu_vendor_priority_cache = [*detected]
        return detected

    def _probe_gpu_vendor_priority(self) -> list[str]:
        cmd = [
            "powershell",
            "-NoProfile",
            "-Command",
            "Get-CimInstance Win32_VideoController | Select-Object -ExpandProperty Name",
        ]
        try:
            probe = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=8,
                check=False,
            )
        except Exception:
            return []

        text = ((probe.stdout or "") + "\n" + (probe.stderr or "")).lower()
        if not text.strip():
            return []

        # Prefer discrete vendors first when multiple adapters are present.
        found: list[str] = []
        if "nvidia" in text:
            found.append("nvidia")
        if "amd" in text or "radeon" in text:
            found.append("amd")
        if "intel" in text:
            found.append("intel")
        return found

    def _ai_advised_encoder_choice(
        self,
        gpu_priority: list[str],
        support: H264EncoderSupport,
        quality_preset: str,
        fps: int,
    ) -> str | None:
        advisor_path = Path(__file__).resolve().parent / "encoder_ai_advisor.py"
        if not advisor_path.exists():
            return None

        try:
            spec = importlib.util.spec_from_file_location("captrix_encoder_ai_advisor", advisor_path)
            if spec is None or spec.loader is None:
                return None
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
        except Exception:
            return None

        recommend = getattr(module, "recommend_encoder", None)
        if recommend is None or not callable(recommend):
            return None

        try:
            choice = recommend(
                {
                    "gpu_priority": [*gpu_priority],
                    "support": {
                        "nvidia": support.nvidia,
                        "intel": support.intel,
                        "amd": support.amd,
                    },
                    "quality_preset": quality_preset,
                    "fps": int(fps),
                }
            )
        except Exception:
            return None

        if isinstance(choice, str):
            normalized = choice.strip().lower()
            if normalized in {"nvidia", "intel", "amd"}:
                return normalized
        return None

    def _probe_h264_encoder_support(self) -> H264EncoderSupport:
        cmd = [self.ffmpeg_path, "-hide_banner", "-encoders"]
        try:
            probe = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
        except Exception as exc:
            return H264EncoderSupport(nvidia=False, intel=False, amd=False, error=str(exc))

        text = f"{probe.stdout or ''}\n{probe.stderr or ''}"
        encoders = self._parse_video_encoder_names(text)
        if probe.returncode != 0 and not encoders:
            err = (probe.stderr or "").strip() or "Failed to query FFmpeg encoders."
            return H264EncoderSupport(nvidia=False, intel=False, amd=False, error=err)

        return H264EncoderSupport(
            nvidia="h264_nvenc" in encoders,
            intel="h264_qsv" in encoders,
            amd="h264_amf" in encoders,
            error=None if encoders else "No video encoders were parsed from FFmpeg output.",
        )

    def _parse_video_encoder_names(self, output: str) -> set[str]:
        encoders: set[str] = set()
        for line in output.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            parts = stripped.split()
            if len(parts) < 2:
                continue
            flags = parts[0].strip()
            if not flags or len(flags) < 3:
                continue
            if any(ch != "." and not ch.isalpha() for ch in flags):
                continue
            if "V" not in flags:
                continue
            name = parts[1].strip()
            if name:
                encoders.add(name)
        return encoders

    def _start_video_command_with_cpu_fallback(
        self,
        cmd_without_output: list[str],
        session_info_base: dict[str, object],
        encoding_plan: VideoEncodingPlan,
        include_audio: bool,
    ) -> None:
        primary_cmd = [*cmd_without_output, *encoding_plan.primary_args]
        if include_audio:
            primary_cmd += self._audio_encode_args()
        else:
            primary_cmd += ["-an"]

        primary_session_info = self._session_info_with_video(
            session_info_base=session_info_base,
            encoding_plan=encoding_plan,
            used_cpu_fallback=False,
            fallback_start_error=None,
        )
        try:
            self._start_command(primary_cmd, session_info=primary_session_info)
            return
        except Exception as primary_error:
            if encoding_plan.cpu_fallback_args is None:
                raise

            fallback_cmd = [*cmd_without_output, *encoding_plan.cpu_fallback_args]
            if include_audio:
                fallback_cmd += self._audio_encode_args()
            else:
                fallback_cmd += ["-an"]

            fallback_session_info = self._session_info_with_video(
                session_info_base=session_info_base,
                encoding_plan=encoding_plan,
                used_cpu_fallback=True,
                fallback_start_error=str(primary_error),
            )
            try:
                self._start_command(fallback_cmd, session_info=fallback_session_info)
                return
            except Exception as fallback_error:
                raise RuntimeError(
                    "Failed to start recording with selected encoder and CPU fallback.\n"
                    f"[Selected encoder]\n{primary_error}\n\n"
                    f"[CPU fallback]\n{fallback_error}"
                ) from fallback_error

    def _session_info_with_video(
        self,
        session_info_base: dict[str, object],
        encoding_plan: VideoEncodingPlan,
        used_cpu_fallback: bool,
        fallback_start_error: str | None,
    ) -> dict[str, object]:
        selected_encoder = "cpu" if used_cpu_fallback else encoding_plan.selected_encoder
        selected_ffmpeg = self._ffmpeg_encoder_name(selected_encoder)
        effective_note = encoding_plan.selection_note
        if used_cpu_fallback and encoding_plan.selected_encoder != "cpu":
            effective_note = (
                f"{self._encoder_display_name(encoding_plan.selected_encoder)} failed to start. "
                "Automatically switched to CPU x264."
            )

        video_info: dict[str, object] = {
            "requested_encoder": encoding_plan.requested_encoder,
            "requested_encoder_label": self._encoder_display_name(encoding_plan.requested_encoder),
            "quality_preset": encoding_plan.quality_preset,
            "quality_preset_label": self._quality_display_name(encoding_plan.quality_preset),
            "selected_encoder": selected_encoder,
            "selected_encoder_label": self._encoder_display_name(selected_encoder),
            "selected_ffmpeg_encoder": selected_ffmpeg,
            "cpu_fallback_applied": used_cpu_fallback,
            "selection_note": effective_note,
            "detected_gpu_support": {
                "nvidia": encoding_plan.support.nvidia,
                "intel": encoding_plan.support.intel,
                "amd": encoding_plan.support.amd,
                "probe_error": encoding_plan.support.error,
            },
        }
        if fallback_start_error:
            video_info["initial_start_error"] = fallback_start_error

        merged = dict(session_info_base)
        merged["video"] = video_info
        return merged

    def _normalize_encoder_preference(self, value: str) -> str:
        key = (value or "").strip().lower()
        mapping = {
            "auto": "auto",
            "cpu": "cpu",
            "cpu (x264)": "cpu",
            "x264": "cpu",
            "nvidia": "nvidia",
            "intel": "intel",
            "amd": "amd",
        }
        return mapping.get(key, "auto")

    def _normalize_quality_preset(self, value: str) -> str:
        key = (value or "").strip().lower()
        mapping = {
            "balanced": "balanced",
            "high quality": "high_quality",
            "high_quality": "high_quality",
            "small file": "small_file",
            "small_file": "small_file",
        }
        return mapping.get(key, "balanced")

    def _encoder_display_name(self, encoder: str) -> str:
        return {
            "auto": "Auto",
            "cpu": "CPU (x264)",
            "nvidia": "NVIDIA",
            "intel": "Intel",
            "amd": "AMD",
        }.get(encoder, encoder)

    def _quality_display_name(self, quality: str) -> str:
        return {
            "balanced": "Balanced",
            "high_quality": "High Quality",
            "small_file": "Small File",
        }.get(quality, quality)

    def _ffmpeg_encoder_name(self, encoder: str) -> str:
        return {
            "cpu": "libx264",
            "nvidia": "h264_nvenc",
            "intel": "h264_qsv",
            "amd": "h264_amf",
        }.get(encoder, "libx264")

    def _is_h264_encoder_supported(self, encoder: str, support: H264EncoderSupport) -> bool:
        if encoder == "nvidia":
            return support.nvidia
        if encoder == "intel":
            return support.intel
        if encoder == "amd":
            return support.amd
        return encoder == "cpu"

    def _start_command(
        self,
        cmd_without_output: list[str],
        session_info: dict[str, object] | None = None,
    ) -> None:
        if self.is_recording():
            raise RuntimeError("Already recording.")

        session_id, mkv_path, mp4_path, manifest_path, lock_path = self._prepare_output_paths()
        cmd = [*cmd_without_output, "-f", "matroska", "-flush_packets", "1", str(mkv_path)]
        log_path = self._prepare_ffmpeg_log_path()

        self._current_mkv = mkv_path
        self._current_mp4 = mp4_path
        self._ffmpeg_log_path = log_path
        self._current_session_id = session_id
        self._current_manifest_path = manifest_path
        self._current_lock_path = lock_path
        try:
            self._acquire_lock(lock_path)
            self._write_manifest(
                manifest_path,
                {
                    "session_id": session_id,
                    "status": "recording",
                    "start_time": datetime.now().isoformat(timespec="seconds"),
                    "updated_at": datetime.now().isoformat(timespec="seconds"),
                    "paths": {
                        "mkv": str(mkv_path),
                        "mp4": str(mp4_path),
                        "log": str(log_path),
                    },
                    "capture": (session_info or {}).get("capture", {}),
                    "resolution": self._manifest_resolution(session_info),
                    "region": self._manifest_region(session_info),
                    "webcam": (session_info or {}).get("webcam", {}),
                    "video": (session_info or {}).get("video", {}),
                    "audio": (session_info or {}).get("audio", {}),
                },
            )
            self._ffmpeg_log_file = log_path.open("w", encoding="utf-8", errors="replace")
            creation_flags = 0
            if hasattr(subprocess, "CREATE_NEW_PROCESS_GROUP"):
                creation_flags = int(subprocess.CREATE_NEW_PROCESS_GROUP)
            self._proc = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                # FFmpeg prints progress continuously; piping without draining can deadlock.
                stdout=subprocess.DEVNULL,
                stderr=self._ffmpeg_log_file,
                text=True,
                creationflags=creation_flags,
            )
            # Fail fast if FFmpeg exits immediately (invalid input/filter/device conflict).
            for _ in range(15):
                if self._proc.poll() is not None:
                    break
                time.sleep(0.1)

            if self._proc.poll() is not None:
                code = int(self._proc.returncode or 0)
                if self._ffmpeg_log_file is not None:
                    try:
                        self._ffmpeg_log_file.flush()
                    except Exception:
                        pass
                details = self._read_log_tail(log_path)
                raise RuntimeError(
                    "FFmpeg exited immediately while starting recording.\n"
                    f"Exit code: {code}\n\n{details}"
                )
        except Exception as e:
            self._update_current_manifest("failed_start", {"error": str(e)})
            self._close_ffmpeg_log()
            self._release_current_lock()
            self._proc = None
            self._current_mkv = None
            self._current_mp4 = None
            self._ffmpeg_log_path = None
            self._current_session_id = None
            self._current_manifest_path = None
            self._current_lock_path = None
            raise

    def _prepare_output_paths(self) -> tuple[str, Path, Path, Path, Path]:
        self.recordings_dir.mkdir(parents=True, exist_ok=True)
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        session_id = f"{stamp}_{uuid.uuid4().hex[:8]}"
        mkv_path = self.temp_dir / f"{session_id}.mkv"
        mp4_path = self.recordings_dir / f"captrix_{session_id}.mp4"
        manifest_path = self.temp_dir / f"{session_id}.json"
        lock_path = self.temp_dir / f"{session_id}.lock"
        return session_id, mkv_path, mp4_path, manifest_path, lock_path

    def _prepare_ffmpeg_log_path(self) -> Path:
        stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        return self.temp_dir / f"captrix_ffmpeg_{stamp}.log"

    def _prepare_screenshot_path(self) -> Path:
        self.recordings_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        return self.recordings_dir / f"captrix_screenshot_{stamp}.png"

    def _acquire_lock(self, lock_path: Path) -> None:
        lock_payload = {
            "pid": os.getpid(),
            "created_at": datetime.now().isoformat(timespec="seconds"),
        }
        encoded = json.dumps(lock_payload, indent=2)
        try:
            fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            with os.fdopen(fd, "w", encoding="utf-8") as fp:
                fp.write(encoded)
        except FileExistsError:
            if self._is_lock_active(lock_path):
                raise RuntimeError(
                    f"A recording lock is still active for this session:\n{lock_path}"
                )
            # Stale lock from previous crash; overwrite safely.
            lock_path.write_text(encoded, encoding="utf-8")

    def _release_current_lock(self) -> None:
        if self._current_lock_path is None:
            return
        try:
            if self._current_lock_path.exists():
                self._current_lock_path.unlink()
        except Exception:
            pass

    def _read_lock_pid(self, lock_path: Path) -> int | None:
        try:
            raw = lock_path.read_text(encoding="utf-8").strip()
        except Exception:
            return None

        if not raw:
            return None
        try:
            data = json.loads(raw)
            if isinstance(data, dict):
                pid = data.get("pid")
                if isinstance(pid, int) and pid > 0:
                    return pid
        except Exception:
            pass

        try:
            pid = int(raw)
            return pid if pid > 0 else None
        except Exception:
            return None

    def _is_lock_active(self, lock_path: Path) -> bool:
        if not lock_path.exists():
            return False
        pid = self._read_lock_pid(lock_path)
        if pid is None:
            return False
        return self._is_pid_alive(pid)

    def _is_pid_alive(self, pid: int) -> bool:
        if pid <= 0:
            return False
        try:
            os.kill(pid, 0)
            return True
        except PermissionError:
            # Process exists but we do not have permission to signal it.
            return True
        except OSError:
            return False
        except Exception:
            return False

    def _write_manifest(self, path: Path, payload: dict[str, object]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_suffix(path.suffix + ".tmp")
        tmp_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        tmp_path.replace(path)

    def _read_manifest(self, path: Path) -> dict[str, object]:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
        except Exception:
            pass
        return {}

    def _manifest_resolution(self, session_info: dict[str, object] | None) -> str:
        if not session_info:
            return "auto"
        capture = session_info.get("capture")
        if not isinstance(capture, dict):
            return "auto"
        region = capture.get("region")
        if isinstance(region, dict):
            width = region.get("width")
            height = region.get("height")
            if isinstance(width, int) and isinstance(height, int) and width > 0 and height > 0:
                return f"{width}x{height}"
        return "auto"

    def _manifest_region(self, session_info: dict[str, object] | None) -> dict[str, object] | None:
        if not session_info:
            return None
        capture = session_info.get("capture")
        if not isinstance(capture, dict):
            return None
        region = capture.get("region")
        if isinstance(region, dict):
            return region
        return None

    def _update_current_manifest(self, status: str, extra: dict[str, object] | None = None) -> None:
        if self._current_manifest_path is None:
            return
        data = self._read_manifest(self._current_manifest_path)
        if not data:
            data = {
                "session_id": self._current_session_id,
                "paths": {
                    "mkv": str(self._current_mkv) if self._current_mkv else None,
                    "mp4": str(self._current_mp4) if self._current_mp4 else None,
                    "log": str(self._ffmpeg_log_path) if self._ffmpeg_log_path else None,
                },
            }
        data["status"] = status
        data["updated_at"] = datetime.now().isoformat(timespec="seconds")
        if extra:
            for key, value in extra.items():
                data[key] = value
        try:
            self._write_manifest(self._current_manifest_path, data)
        except Exception:
            pass

    def _finalize_manifest(
        self,
        manifest_path: Path | None,
        status: str,
        extra: dict[str, object] | None = None,
    ) -> None:
        if manifest_path is None:
            return
        data = self._read_manifest(manifest_path)
        if not data:
            return
        data["status"] = status
        data["updated_at"] = datetime.now().isoformat(timespec="seconds")
        if status == "finalized":
            data["finalized_at"] = datetime.now().isoformat(timespec="seconds")
        if extra:
            for key, value in extra.items():
                data[key] = value
        try:
            self._write_manifest(manifest_path, data)
        except Exception:
            pass

    def list_unfinished_sessions(self) -> list[RecoverySession]:
        sessions: list[RecoverySession] = []
        seen_mkvs: set[Path] = set()

        for manifest_path in sorted(self.temp_dir.glob("*.json")):
            data = self._read_manifest(manifest_path)
            if not data:
                continue
            status = str(data.get("status") or "").strip().lower() or "unknown"
            paths = data.get("paths")
            mkv_path = None
            mp4_path = None
            if isinstance(paths, dict):
                raw_mkv = paths.get("mkv")
                raw_mp4 = paths.get("mp4")
                if isinstance(raw_mkv, str) and raw_mkv.strip():
                    mkv_path = Path(raw_mkv)
                if isinstance(raw_mp4, str) and raw_mp4.strip():
                    mp4_path = Path(raw_mp4)
            if mkv_path is None:
                sid = str(data.get("session_id") or manifest_path.stem)
                mkv_path = self.temp_dir / f"{sid}.mkv"
            if mp4_path is None:
                mp4_path = self.recordings_dir / f"captrix_{mkv_path.stem}.mp4"

            if not mkv_path.exists():
                continue
            try:
                seen_mkvs.add(mkv_path.resolve())
            except Exception:
                seen_mkvs.add(mkv_path)

            if status == "finalized":
                continue
            if self._is_lock_active(self.temp_dir / f"{manifest_path.stem}.lock"):
                # A live lock means another process still owns this session.
                continue

            try:
                size_bytes = mkv_path.stat().st_size
            except OSError:
                size_bytes = 0
            sessions.append(
                RecoverySession(
                    session_id=str(data.get("session_id") or mkv_path.stem),
                    mkv_path=mkv_path,
                    mp4_path=mp4_path,
                    manifest_path=manifest_path,
                    start_time=(str(data.get("start_time")) if data.get("start_time") else None),
                    status=status,
                    size_bytes=size_bytes,
                )
            )

        for mkv_path in sorted(self.temp_dir.glob("*.mkv")):
            try:
                resolved = mkv_path.resolve()
            except Exception:
                resolved = mkv_path
            if resolved in seen_mkvs:
                continue
            try:
                size_bytes = mkv_path.stat().st_size
            except OSError:
                size_bytes = 0
            if size_bytes <= 0:
                continue
            sessions.append(
                RecoverySession(
                    session_id=mkv_path.stem,
                    mkv_path=mkv_path,
                    mp4_path=self.recordings_dir / f"captrix_{mkv_path.stem}.mp4",
                    manifest_path=None,
                    start_time=None,
                    status="unknown",
                    size_bytes=size_bytes,
                )
            )

        sessions.sort(key=lambda s: s.mkv_path.stat().st_mtime if s.mkv_path.exists() else 0, reverse=True)
        return sessions

    def recover_session(self, session: RecoverySession) -> Path:
        if self.is_recording():
            raise RuntimeError("Stop current recording before recovery.")
        if not session.mkv_path.exists() or session.mkv_path.stat().st_size == 0:
            raise RuntimeError(f"Recovery source is missing or empty:\n{session.mkv_path}")
        self._remux_to_mp4(session.mkv_path, session.mp4_path)
        if session.manifest_path is not None and session.manifest_path.exists():
            self._finalize_manifest(
                session.manifest_path,
                "finalized",
                extra={"recovered": True, "recovered_at": datetime.now().isoformat(timespec="seconds")},
            )
        return session.mp4_path

    def delete_session(self, session: RecoverySession) -> None:
        targets = [session.mkv_path]
        if session.manifest_path is not None:
            targets.append(session.manifest_path)
        targets.append(self.temp_dir / f"{session.session_id}.lock")
        for target in targets:
            try:
                if target.exists():
                    target.unlink()
            except Exception:
                pass

    def cleanup_old_temp_files(self, max_age_days: int = 7) -> int:
        cutoff = time.time() - max(1, int(max_age_days)) * 86400
        removed = 0
        for manifest_path in self.temp_dir.glob("*.json"):
            data = self._read_manifest(manifest_path)
            if not data:
                continue
            if str(data.get("status") or "").strip().lower() != "finalized":
                continue
            try:
                if manifest_path.stat().st_mtime > cutoff:
                    continue
            except OSError:
                continue
            paths = data.get("paths")
            mkv_path: Path | None = None
            if isinstance(paths, dict):
                raw_mkv = paths.get("mkv")
                if isinstance(raw_mkv, str) and raw_mkv.strip():
                    mkv_path = Path(raw_mkv)
            for target in (mkv_path, manifest_path, self.temp_dir / f"{manifest_path.stem}.lock"):
                if target is None:
                    continue
                try:
                    if target.exists():
                        target.unlink()
                        removed += 1
                except Exception:
                    pass
        return removed

    def list_recordings(
        self,
        extensions: tuple[str, ...] | None = None,
        search_query: str | None = None,
    ) -> list[RecordingLibraryItem]:
        self.recordings_dir.mkdir(parents=True, exist_ok=True)
        exts = {ext.lower() for ext in (extensions or tuple()) if ext}
        query = (search_query or "").strip().lower()

        files: list[Path] = []
        for path in self.recordings_dir.iterdir():
            if not path.is_file():
                continue
            if exts and path.suffix.lower() not in exts:
                continue
            if query and query not in path.name.lower():
                continue
            files.append(path)

        files.sort(key=lambda p: p.stat().st_mtime if p.exists() else 0, reverse=True)

        items: list[RecordingLibraryItem] = []
        for path in files:
            try:
                stat = path.stat()
            except OSError:
                continue
            items.append(
                RecordingLibraryItem(
                    path=path,
                    filename=path.name,
                    duration_sec=self._probe_duration_seconds(path),
                    size_bytes=stat.st_size,
                    created_at=datetime.fromtimestamp(stat.st_ctime),
                )
            )
        return items

    def rename_recording(self, source: Path, new_name: str) -> Path:
        if not source.exists() or not source.is_file():
            raise RuntimeError(f"Recording file not found:\n{source}")

        cleaned = new_name.strip()
        if not cleaned:
            raise RuntimeError("New filename cannot be empty.")
        if any(ch in cleaned for ch in '<>:"/\\|?*'):
            raise RuntimeError("Filename contains invalid characters.")

        destination = source.with_name(cleaned)
        if destination.suffix == "":
            destination = destination.with_suffix(source.suffix)
        if destination == source:
            return source
        if destination.exists():
            raise RuntimeError(f"A file with this name already exists:\n{destination}")

        source.rename(destination)
        return destination

    def delete_recording(self, target: Path) -> None:
        if not target.exists():
            return
        if not target.is_file():
            raise RuntimeError(f"Not a file:\n{target}")
        target.unlink()

    def _resolve_ffprobe_path(self) -> str:
        if self._ffprobe_path_cache:
            return self._ffprobe_path_cache

        ffmpeg_bin = Path(self.ffmpeg_path)
        if ffmpeg_bin.exists():
            candidates = [
                ffmpeg_bin.with_name("ffprobe.exe"),
                ffmpeg_bin.with_name("ffprobe"),
            ]
            for candidate in candidates:
                if candidate.exists():
                    self._ffprobe_path_cache = str(candidate)
                    return self._ffprobe_path_cache

        self._ffprobe_path_cache = "ffprobe.exe" if os.name == "nt" else "ffprobe"
        return self._ffprobe_path_cache

    def _probe_duration_seconds(self, media_path: Path) -> float | None:
        if media_path.suffix.lower() in {".png", ".jpg", ".jpeg", ".bmp", ".webp"}:
            return None

        ffprobe_path = self._resolve_ffprobe_path()
        probe_cmd = [
            ffprobe_path,
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(media_path),
        ]
        try:
            result = subprocess.run(
                probe_cmd,
                capture_output=True,
                text=True,
                timeout=8,
            )
        except Exception:
            return None

        if result.returncode != 0:
            return None
        raw = (result.stdout or "").strip()
        if not raw:
            return None
        try:
            value = float(raw)
            return value if value >= 0 else None
        except ValueError:
            return None

    def _run_single_frame_capture(
        self,
        cmd_without_output: list[str],
        output_path: Path,
        timeout_sec: int = 20,
    ) -> None:
        if self.is_recording():
            raise RuntimeError("Stop current recording before taking a screenshot.")

        output_path.parent.mkdir(parents=True, exist_ok=True)

        cmd = [
            *cmd_without_output,
            "-frames:v",
            "1",
            str(output_path),
        ]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_sec)
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError("Screenshot capture timed out.") from exc

        if result.returncode == 0 and output_path.exists() and output_path.stat().st_size > 0:
            return

        try:
            if output_path.exists():
                output_path.unlink()
        except Exception:
            pass

        stderr = (result.stderr or "").strip()
        if not stderr:
            stderr = "FFmpeg screenshot command failed."
        raise RuntimeError(stderr)

    def _audio_input_args(self, mic_name: str) -> list[str]:
        if not mic_name.strip():
            raise RuntimeError("Microphone source is required.")
        return [
            "-thread_queue_size",
            "512",
            "-f",
            "dshow",
            "-i",
            f"audio={mic_name}",
        ]

    def _looks_like_webcam_input_error(self, error_text: str, device_name: str) -> bool:
        text = (error_text or "").lower()
        if not text:
            return False

        webcam_tokens = (
            "webcam overlay could not start",
            "could not read webcam frames",
            "error during demuxing",
            "i/o error",
            "could not find video device",
            "no such device",
        )
        if any(token in text for token in webcam_tokens):
            return True

        device = (device_name or "").strip().lower()
        if device and device in text:
            return True

        # FFmpeg dshow failures for webcam inputs often include video=... and dshow markers.
        return "dshow" in text and "video=" in text and "error" in text

    def _system_audio_input_args(self, device_name: str, backend: str = "dshow") -> list[str]:
        if not device_name.strip():
            raise RuntimeError("System audio source is required.")

        key = backend.lower().strip()
        if key == "wasapi":
            # Use default render endpoint loopback when available.
            target = device_name.strip() or "default"
            return [
                "-thread_queue_size",
                "512",
                "-f",
                "wasapi",
                "-i",
                target,
            ]

        return [
            "-thread_queue_size",
            "512",
            "-f",
            "dshow",
            "-i",
            f"audio={device_name}",
        ]

    def _webcam_input_args(self, device_name: str) -> list[str]:
        if not device_name.strip():
            raise RuntimeError("Webcam device is required.")
        key = device_name.strip().lower()
        cached = self._webcam_args_cache.get(key)
        if cached is not None:
            return [*cached]

        selected = self._select_working_webcam_args(device_name)
        self._webcam_args_cache[key] = [*selected]
        return selected

    def _candidate_webcam_input_args(self, device_name: str) -> list[list[str]]:
        base = [
            "-thread_queue_size",
            "512",
            "-analyzeduration",
            "200M",
            "-probesize",
            "200M",
            "-f",
            "dshow",
            "-rtbufsize",
            "256M",
            "-framerate",
            "30",
        ]
        return [
            # Prefer MJPEG mode first (commonly the most stable on USB UVC webcams).
            [*base, "-video_size", "1280x720", "-vcodec", "mjpeg", "-i", f"video={device_name}"],
            # Let dshow negotiate automatically as primary fallback.
            [*base, "-i", f"video={device_name}"],
            # Conservative raw format fallback.
            [*base, "-video_size", "640x480", "-pixel_format", "yuyv422", "-i", f"video={device_name}"],
        ]

    def _select_working_webcam_args(self, device_name: str) -> list[str]:
        last_error = ""
        for args in self._candidate_webcam_input_args(device_name):
            probe_cmd = [
                self.ffmpeg_path,
                "-hide_banner",
                "-loglevel",
                "error",
                *args,
                "-t",
                "2",
                "-f",
                "null",
                "-",
            ]
            try:
                probe = subprocess.run(probe_cmd, capture_output=True, text=True, timeout=10)
            except subprocess.TimeoutExpired:
                last_error = "Webcam probe timed out."
                continue

            stderr = (probe.stderr or "").strip()
            stderr_lower = stderr.lower()
            has_demux_error = "error during demuxing" in stderr_lower
            has_empty_output = "output file is empty" in stderr_lower
            has_no_frames = "no filtered frames for output stream" in stderr_lower

            if probe.returncode == 0 and not (has_demux_error or has_empty_output or has_no_frames):
                return args
            if stderr:
                last_error = stderr

        if not last_error:
            last_error = "Failed to open webcam with all fallback input profiles."
        raise WebcamInputError(
            "Webcam overlay could not start because FFmpeg could not read webcam frames.\n"
            f"Device: {device_name}\n{last_error}"
        )

    def _av_sync_args(self) -> list[str]:
        return ["-af", "aresample=48000:async=1:first_pts=0:min_hard_comp=0.100"]

    def _audio_mix_filter_graph(
        self,
        mic_input_index: int,
        system_input_index: int | None,
        mic_volume_percent: int = 100,
        system_volume_percent: int = 100,
    ) -> str:
        mic_gain = self._volume_gain(mic_volume_percent)
        parts = [
            f"[{mic_input_index}:a]aresample=48000:async=1:first_pts=0:min_hard_comp=0.100,"
            f"volume={mic_gain:.3f}[mic_a]",
        ]

        if system_input_index is None:
            parts.append("[mic_a]anull[aout]")
            return ";".join(parts)

        sys_gain = self._volume_gain(system_volume_percent)
        parts.append(
            f"[{system_input_index}:a]aresample=48000:async=1:first_pts=0:min_hard_comp=0.100,"
            f"volume={sys_gain:.3f}[sys_a]"
        )
        parts.append(
            "[mic_a][sys_a]amix=inputs=2:duration=longest:dropout_transition=2:normalize=0,"
            "aresample=48000:async=1:first_pts=0:min_hard_comp=0.100[aout]"
        )
        return ";".join(parts)

    def _volume_gain(self, percent: int) -> float:
        clamped = max(0, min(200, int(percent)))
        return float(clamped) / 100.0

    def _video_encode_args(self, preset: str = "veryfast", crf: str = "23", fps: int = 30) -> list[str]:
        return self._cpu_video_encode_args(preset=preset, crf=crf, fps=fps)

    def _cpu_video_encode_args(self, preset: str = "veryfast", crf: str = "23", fps: int = 30) -> list[str]:
        args = [
            "-c:v",
            "libx264",
            "-preset",
            preset,
            "-crf",
            crf,
            "-pix_fmt",
            "yuv420p",
            "-r",
            str(max(1, int(fps))),
            "-fps_mode",
            "cfr",
        ]
        return args

    def _video_encode_args_for_encoder(self, encoder: str, quality_preset: str, fps: int) -> list[str]:
        quality = self._normalize_quality_preset(quality_preset)
        target_fps = max(1, int(fps))

        if encoder == "cpu":
            cpu_map = {
                "balanced": ("veryfast", "23"),
                "high_quality": ("faster", "20"),
                "small_file": ("veryfast", "28"),
            }
            preset, crf = cpu_map.get(quality, cpu_map["balanced"])
            return self._cpu_video_encode_args(preset=preset, crf=crf, fps=target_fps)

        if encoder == "nvidia":
            nvenc_map = {
                "balanced": ("p4", "23"),
                "high_quality": ("p5", "19"),
                "small_file": ("p3", "28"),
            }
            preset, cq = nvenc_map.get(quality, nvenc_map["balanced"])
            return [
                "-c:v",
                "h264_nvenc",
                "-preset",
                preset,
                "-cq",
                cq,
                "-pix_fmt",
                "yuv420p",
                "-r",
                str(target_fps),
                "-fps_mode",
                "cfr",
            ]

        if encoder == "intel":
            qsv_map = {
                "balanced": "23",
                "high_quality": "19",
                "small_file": "28",
            }
            global_quality = qsv_map.get(quality, qsv_map["balanced"])
            return [
                "-c:v",
                "h264_qsv",
                "-global_quality",
                global_quality,
                "-pix_fmt",
                "nv12",
                "-r",
                str(target_fps),
                "-fps_mode",
                "cfr",
            ]

        if encoder == "amd":
            amf_map = {
                "balanced": "balanced",
                "high_quality": "quality",
                "small_file": "speed",
            }
            quality_value = amf_map.get(quality, amf_map["balanced"])
            return [
                "-c:v",
                "h264_amf",
                "-quality",
                quality_value,
                "-pix_fmt",
                "nv12",
                "-r",
                str(target_fps),
                "-fps_mode",
                "cfr",
            ]

        # Unknown key falls back to CPU defaults.
        return self._cpu_video_encode_args(preset="veryfast", crf="23", fps=target_fps)

    def _audio_encode_args(self, bitrate: str = "160k") -> list[str]:
        return [
            "-c:a",
            "aac",
            "-b:a",
            bitrate,
            "-ar",
            "48000",
            "-ac",
            "2",
        ]

    def _input_timestamp_args(self) -> list[str]:
        return [
            "-fflags",
            "+genpts",
            "-avoid_negative_ts",
            "make_zero",
        ]

    def _build_screen_input_args(
        self, region: CaptureRegion | None, region_mode: str
    ) -> list[str]:
        args, _ = self._build_screen_input_with_optional_filter(
            region=region,
            region_mode=region_mode,
            for_complex_filter=False,
        )
        return args

    def _build_screen_input_with_optional_filter(
        self,
        region: CaptureRegion | None,
        region_mode: str,
        for_complex_filter: bool,
    ) -> tuple[list[str], str | None]:
        mode = region_mode.lower().strip()
        if mode not in {"crop", "direct"}:
            raise RuntimeError(f"Unsupported region mode: {region_mode}")

        if region is None:
            return (
                [
                    "-f",
                    "gdigrab",
                    "-framerate",
                    "30",
                    "-i",
                    "desktop",
                ],
                None,
            )

        if region.width <= 0 or region.height <= 0:
            raise RuntimeError("Region dimensions must be positive.")

        normalized = self._normalize_even_region(region)
        width = normalized.width
        height = normalized.height
        x = normalized.x
        y = normalized.y

        if mode == "direct":
            # Option B: direct region capture by gdigrab input options.
            return (
                [
                    "-f",
                    "gdigrab",
                    "-framerate",
                    "30",
                    "-offset_x",
                    str(x),
                    "-offset_y",
                    str(y),
                    "-video_size",
                    f"{width}x{height}",
                    "-i",
                    "desktop",
                ],
                None,
            )

        # Option A (preferred): full desktop input + crop filter.
        crop_x, crop_y = self._crop_origin_for_region(normalized)
        crop_filter = f"crop={width}:{height}:{crop_x}:{crop_y}"
        if for_complex_filter:
            return (
                [
                    "-f",
                    "gdigrab",
                    "-framerate",
                    "30",
                    "-i",
                    "desktop",
                ],
                crop_filter,
            )

        return (
            [
                "-f",
                "gdigrab",
                "-framerate",
                "30",
                "-i",
                "desktop",
                "-vf",
                crop_filter,
            ],
            None,
        )

    def _window_capture_input_args(self, window_title: str, fps: int, hide_mouse: bool) -> list[str]:
        if not window_title.strip():
            raise RuntimeError("Window title is required for capture.")

        args = [
            "-f",
            "gdigrab",
            "-framerate",
            str(fps),
        ]
        if hide_mouse:
            args += ["-draw_mouse", "0"]
        args += ["-i", f"title={window_title}"]
        return args

    def _webcam_overlay_filter_graph(
        self,
        overlay: WebcamOverlay,
        base_filter: str | None = None,
    ) -> str:
        size = max(16, min(70, int(overlay.size_percent)))
        margin = max(0, int(overlay.margin_px))
        position_expr = self._overlay_position_expression(overlay.position, margin)
        # Keep final encoded overlay size closer to UI preview geometry.
        scale_expr = f"w='trunc(min(main_w\\,main_h)*{size}/100/2)*2':h=-2"

        # gdigrab and dshow often have unrelated starting timestamps.
        # Normalize both streams to t=0 so overlay framesync works reliably.
        if base_filter:
            filter_graph = (
                f"[0:v]setpts=PTS-STARTPTS,{base_filter}[base0];"
                "[1:v]setpts=PTS-STARTPTS[cam0];"
                f"[cam0][base0]scale2ref={scale_expr}[cam][base];"
                "[cam]format=yuv420p,drawbox=x=0:y=0:w=iw:h=ih:color=white@0.95:t=3[cam_box];"
                f"[base][cam_box]overlay={position_expr}:format=auto:eof_action=pass:repeatlast=1[vtmp];"
                "[vtmp]scale='trunc(iw/2)*2':'trunc(ih/2)*2',format=yuv420p[vout]"
            )
        else:
            filter_graph = (
                "[0:v]setpts=PTS-STARTPTS[base0];"
                "[1:v]setpts=PTS-STARTPTS[cam0];"
                f"[cam0][base0]scale2ref={scale_expr}[cam][base];"
                "[cam]format=yuv420p,drawbox=x=0:y=0:w=iw:h=ih:color=white@0.95:t=3[cam_box];"
                f"[base][cam_box]overlay={position_expr}:format=auto:eof_action=pass:repeatlast=1[vtmp];"
                "[vtmp]scale='trunc(iw/2)*2':'trunc(ih/2)*2',format=yuv420p[vout]"
            )

        return filter_graph

    def _overlay_position_expression(self, position: str, margin: int) -> str:
        key = position.lower().strip()
        if key == "top_left":
            return f"{margin}:{margin}"
        if key == "top_right":
            return f"main_w-overlay_w-{margin}:{margin}"
        if key == "bottom_left":
            return f"{margin}:main_h-overlay_h-{margin}"
        return f"main_w-overlay_w-{margin}:main_h-overlay_h-{margin}"

    def _normalize_even_region(self, region: CaptureRegion) -> CaptureRegion:
        width = int(region.width)
        height = int(region.height)
        if width % 2 != 0:
            width -= 1
        if height % 2 != 0:
            height -= 1
        if width < 2 or height < 2:
            raise RuntimeError("Selected region is too small after even-dimension normalization.")
        return CaptureRegion(
            x=int(region.x),
            y=int(region.y),
            width=width,
            height=height,
        )

    def _crop_origin_for_region(self, region: CaptureRegion) -> tuple[int, int]:
        virtual_x, virtual_y = self._virtual_screen_origin()
        crop_x = region.x - virtual_x
        crop_y = region.y - virtual_y
        if crop_x < 0 or crop_y < 0:
            raise RuntimeError("Selected region is outside the virtual screen bounds.")
        return crop_x, crop_y

    def _virtual_screen_origin(self) -> tuple[int, int]:
        if not hasattr(ctypes, "windll"):
            return (0, 0)

        try:
            user32 = ctypes.windll.user32
            sm_x_virtual_screen = 76
            sm_y_virtual_screen = 77
            return (
                int(user32.GetSystemMetrics(sm_x_virtual_screen)),
                int(user32.GetSystemMetrics(sm_y_virtual_screen)),
            )
        except Exception:
            return (0, 0)

    def stop_recording(self) -> RecordingResult:
        if self._proc is None or self._current_mkv is None or self._current_mp4 is None:
            raise RuntimeError("No active recording session.")

        proc = self._proc
        mkv_path = self._current_mkv
        mp4_path = self._current_mp4
        manifest_path = self._current_manifest_path

        try:
            stopped_cleanly = True
            if proc.poll() is None:
                self._request_ffmpeg_quit(proc)
                stopped_cleanly = self._wait_for_ffmpeg_exit(proc)

            if not mkv_path.exists() or mkv_path.stat().st_size == 0:
                log_tail = self._read_log_tail(self._ffmpeg_log_path)
                extra = (
                    "\nFFmpeg may not have stopped cleanly."
                    if not stopped_cleanly
                    else ""
                )
                raise RuntimeError(
                    f"Recording file was not produced or is empty:\n{mkv_path}"
                    f"{extra}\n\n{log_tail}"
                )

            self._remux_to_mp4(mkv_path, mp4_path)
            self._finalize_manifest(
                manifest_path,
                "finalized",
                extra={
                    "mkv_size_bytes": mkv_path.stat().st_size if mkv_path.exists() else 0,
                    "mp4_size_bytes": mp4_path.stat().st_size if mp4_path.exists() else 0,
                    "stopped_cleanly": stopped_cleanly,
                },
            )
            self.cleanup_old_temp_files(max_age_days=10)
            return RecordingResult(mkv_path=mkv_path, mp4_path=mp4_path)
        except Exception as e:
            self._finalize_manifest(
                manifest_path,
                "failed_stop",
                extra={"error": str(e)},
            )
            raise
        finally:
            if proc.stdin:
                try:
                    proc.stdin.close()
                except Exception:
                    pass

            self._close_ffmpeg_log()
            self._release_current_lock()
            self._proc = None
            self._current_mkv = None
            self._current_mp4 = None
            self._ffmpeg_log_path = None
            self._current_session_id = None
            self._current_manifest_path = None
            self._current_lock_path = None

    def _request_ffmpeg_quit(self, proc: subprocess.Popen[str]) -> None:
        if not proc.stdin:
            return

        try:
            proc.stdin.write("q\n")
            proc.stdin.flush()
        except Exception:
            pass

    def _wait_for_ffmpeg_exit(self, proc: subprocess.Popen[str]) -> bool:
        try:
            proc.wait(timeout=20)
            return True
        except subprocess.TimeoutExpired:
            pass

        # Try a graceful interrupt on Windows process groups before terminate/kill.
        if proc.poll() is None and hasattr(signal, "CTRL_BREAK_EVENT"):
            try:
                proc.send_signal(signal.CTRL_BREAK_EVENT)  # type: ignore[arg-type]
                proc.wait(timeout=6)
                return False
            except Exception:
                pass

        if proc.poll() is None:
            # Fall back to terminate, then kill only if absolutely necessary.
            proc.terminate()

        try:
            proc.wait(timeout=8)
            return False
        except subprocess.TimeoutExpired:
            pass

        if proc.poll() is None:
            proc.kill()

        try:
            proc.wait(timeout=4)
        except subprocess.TimeoutExpired:
            pass

        return False

    def _remux_to_mp4(self, mkv_path: Path, mp4_path: Path) -> None:
        mp4_path.parent.mkdir(parents=True, exist_ok=True)
        remux_cmd = [
            self.ffmpeg_path,
            "-y",
            "-i",
            str(mkv_path),
            "-map",
            "0",
            "-dn",
            "-c",
            "copy",
            "-movflags",
            "+faststart",
            str(mp4_path),
        ]
        remux = subprocess.run(remux_cmd, capture_output=True, text=True)

        if remux.returncode == 0 and mp4_path.exists() and mp4_path.stat().st_size > 0:
            return

        try:
            if mp4_path.exists():
                mp4_path.unlink()
        except Exception:
            pass

        remux_stderr = (remux.stderr or "").strip()
        capture_tail = self._read_log_tail(self._ffmpeg_log_path)
        raise RuntimeError(
            "Finalize failed while remuxing MKV to MP4.\n"
            f"Temp MKV: {mkv_path}\n"
            f"Target MP4: {mp4_path}\n\n"
            f"[Copy Remux]\n{remux_stderr}\n\n"
            f"{capture_tail}"
        )

    def _read_log_tail(self, log_path: Path | None, max_lines: int = 16) -> str:
        if log_path is None or not log_path.exists():
            return "No FFmpeg log available."

        if self._ffmpeg_log_file is not None and self._ffmpeg_log_path == log_path:
            try:
                self._ffmpeg_log_file.flush()
            except Exception:
                pass

        try:
            data = log_path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            return f"Failed to read FFmpeg log: {log_path}"

        lines = [line for line in data.splitlines() if line.strip()]
        if not lines:
            return f"FFmpeg log is empty: {log_path}"

        tail = lines[-max_lines:]
        clipped: list[str] = []
        for line in tail:
            if len(line) > 220:
                clipped.append(line[:217] + "...")
            else:
                clipped.append(line)
        return "FFmpeg log (tail):\n" + "\n".join(clipped)

    def _close_ffmpeg_log(self) -> None:
        if self._ffmpeg_log_file is None:
            return
        try:
            self._ffmpeg_log_file.flush()
        except Exception:
            pass
        try:
            self._ffmpeg_log_file.close()
        except Exception:
            pass
        self._ffmpeg_log_file = None
