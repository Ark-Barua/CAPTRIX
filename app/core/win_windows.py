from __future__ import annotations

import ctypes


def list_visible_window_titles() -> list[str]:
    if not hasattr(ctypes, "windll"):
        return []

    user32 = ctypes.windll.user32
    titles: list[str] = []
    seen: set[str] = set()

    enum_windows_proc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

    @enum_windows_proc
    def _enum_proc(hwnd, _lparam):
        if not user32.IsWindowVisible(hwnd):
            return True

        length = user32.GetWindowTextLengthW(hwnd)
        if length <= 0:
            return True

        buffer = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buffer, length + 1)
        title = buffer.value.strip()
        if not title:
            return True

        if title in {"Program Manager"}:
            return True

        if title not in seen:
            seen.add(title)
            titles.append(title)
        return True

    user32.EnumWindows(_enum_proc, 0)
    titles.sort(key=str.casefold)
    return titles


def get_foreground_window_title() -> str | None:
    if not hasattr(ctypes, "windll"):
        return None

    user32 = ctypes.windll.user32
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return None

    length = user32.GetWindowTextLengthW(hwnd)
    if length <= 0:
        return None

    buffer = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buffer, length + 1)
    title = buffer.value.strip()
    return title or None
