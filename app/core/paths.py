from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class AppPaths:
    app_dir: Path
    settings_dir: Path
    recordings_dir: Path
    temp_dir: Path


def _app_base(app_name: str) -> Path:
    return Path.home() / f".{app_name.lower()}"


def _settings_file(settings_dir: Path) -> Path:
    return settings_dir / "app_settings.json"


def _load_settings(settings_file: Path) -> dict:
    if not settings_file.exists():
        return {}

    try:
        return json.loads(settings_file.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_settings(settings_file: Path, data: dict) -> None:
    settings_file.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def set_recordings_dir(directory: str | Path, app_name: str = "CAPTRIX") -> AppPaths:
    base = _app_base(app_name)
    settings_dir = _ensure_dir(base / "settings")
    settings_file = _settings_file(settings_dir)

    selected = Path(directory).expanduser()
    if not selected.is_absolute():
        selected = (Path.cwd() / selected).resolve()

    _ensure_dir(selected)

    data = _load_settings(settings_file)
    data["recordings_dir"] = str(selected)
    _save_settings(settings_file, data)

    return get_app_paths(app_name)


def get_app_paths(app_name: str = "CAPTRIX") -> AppPaths:
    base = _app_base(app_name)

    settings_dir = base / "settings"
    default_recordings_dir = base / "recordings"
    temp_dir = base / "temp"

    _ensure_dir(settings_dir)
    _ensure_dir(temp_dir)

    settings_data = _load_settings(_settings_file(settings_dir))
    raw_recordings = settings_data.get("recordings_dir")
    recordings_dir = (
        Path(raw_recordings).expanduser()
        if isinstance(raw_recordings, str) and raw_recordings.strip()
        else default_recordings_dir
    )

    try:
        _ensure_dir(recordings_dir)
    except Exception:
        recordings_dir = _ensure_dir(default_recordings_dir)

    return AppPaths(
        app_dir=base,
        settings_dir=settings_dir,
        recordings_dir=recordings_dir,
        temp_dir=temp_dir,
    )
