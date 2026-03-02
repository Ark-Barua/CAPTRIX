from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPainterPath, QPen, QPixmap


def _color(hex_code: str) -> QColor:
    return QColor(hex_code)


def build_app_icon(size: int = 32) -> QIcon:
    return _render_icon("app", size=size)


def build_icon(name: str, size: int = 18) -> QIcon:
    return _render_icon(name, size=size)


def _render_icon(name: str, size: int) -> QIcon:
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)

    dispatch = {
        "app": _draw_app,
        "play": _draw_play,
        "stop": _draw_stop,
        "rec": _draw_rec,
        "region": _draw_region,
        "clear": _draw_clear,
        "folder": _draw_folder,
        "settings": _draw_settings,
        "recordings": _draw_recordings,
        "temp": _draw_temp,
        "ffmpeg": _draw_ffmpeg,
        "mic": _draw_mic,
        "capture_region": _draw_capture_region,
        "home": _draw_home,
        "general": _draw_general,
        "video": _draw_video,
        "image": _draw_image,
        "about": _draw_about,
        "fullscreen": _draw_fullscreen,
        "window": _draw_window,
        "device": _draw_device,
        "game": _draw_game,
        "audio": _draw_audio,
        "screenshot": _draw_screenshot,
    }
    draw_fn = dispatch.get(name, _draw_default)
    draw_fn(painter, size)
    painter.end()
    return QIcon(pixmap)


def _draw_default(p: QPainter, size: int) -> None:
    p.setPen(QPen(_color("#d7e9ff"), 1.7))
    p.drawEllipse(QRectF(size * 0.2, size * 0.2, size * 0.6, size * 0.6))


def _draw_app(p: QPainter, size: int) -> None:
    screen = QRectF(size * 0.14, size * 0.14, size * 0.72, size * 0.54)
    stand = QRectF(size * 0.42, size * 0.69, size * 0.16, size * 0.06)
    base = QRectF(size * 0.31, size * 0.77, size * 0.38, size * 0.06)

    p.setPen(QPen(_color("#7ec9ff"), 1.3))
    p.setBrush(_color("#133b63"))
    p.drawRoundedRect(screen, size * 0.08, size * 0.08)

    glow = QRectF(screen.left() + size * 0.03, screen.top() + size * 0.03, screen.width() * 0.8, screen.height() * 0.55)
    p.fillRect(glow, _color("#36bdf4"))

    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(_color("#7da6c9"))
    p.drawRoundedRect(stand, size * 0.02, size * 0.02)
    p.drawRoundedRect(base, size * 0.02, size * 0.02)


def _draw_play(p: QPainter, size: int) -> None:
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(_color("#2ce49f"))
    path = QPainterPath()
    path.moveTo(size * 0.34, size * 0.22)
    path.lineTo(size * 0.34, size * 0.78)
    path.lineTo(size * 0.78, size * 0.5)
    path.closeSubpath()
    p.drawPath(path)


def _draw_stop(p: QPainter, size: int) -> None:
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(_color("#ff7e93"))
    p.drawRoundedRect(QRectF(size * 0.24, size * 0.24, size * 0.52, size * 0.52), size * 0.1, size * 0.1)


def _draw_rec(p: QPainter, size: int) -> None:
    p.setPen(QPen(_color("#ff738f"), 1.6))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawEllipse(QRectF(size * 0.14, size * 0.14, size * 0.72, size * 0.72))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(_color("#ff546f"))
    p.drawEllipse(QRectF(size * 0.34, size * 0.34, size * 0.32, size * 0.32))


def _draw_region(p: QPainter, size: int) -> None:
    pen = QPen(_color("#70d6ff"), 1.8)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    _draw_crop_corners(p, QRectF(size * 0.16, size * 0.16, size * 0.68, size * 0.68))
    p.setPen(QPen(_color("#d7e9ff"), 1.4))
    p.drawLine(QPointF(size * 0.5, size * 0.36), QPointF(size * 0.5, size * 0.64))
    p.drawLine(QPointF(size * 0.36, size * 0.5), QPointF(size * 0.64, size * 0.5))


def _draw_clear(p: QPainter, size: int) -> None:
    p.setPen(QPen(_color("#9ec7f0"), 1.6))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawEllipse(QRectF(size * 0.18, size * 0.18, size * 0.64, size * 0.64))
    p.setPen(QPen(_color("#ff8aa0"), 1.8))
    p.drawLine(QPointF(size * 0.34, size * 0.34), QPointF(size * 0.66, size * 0.66))
    p.drawLine(QPointF(size * 0.66, size * 0.34), QPointF(size * 0.34, size * 0.66))


def _draw_folder(p: QPainter, size: int) -> None:
    body = QRectF(size * 0.12, size * 0.3, size * 0.76, size * 0.5)
    tab = QRectF(size * 0.18, size * 0.2, size * 0.28, size * 0.16)

    p.setPen(QPen(_color("#98c5ed"), 1.2))
    p.setBrush(_color("#2f5a86"))
    p.drawRoundedRect(body, size * 0.06, size * 0.06)
    p.setBrush(_color("#3f79af"))
    p.drawRoundedRect(tab, size * 0.04, size * 0.04)


def _draw_settings(p: QPainter, size: int) -> None:
    p.setPen(QPen(_color("#d7e9ff"), 1.5))
    y1 = size * 0.3
    y2 = size * 0.5
    y3 = size * 0.7
    p.drawLine(QPointF(size * 0.18, y1), QPointF(size * 0.82, y1))
    p.drawLine(QPointF(size * 0.18, y2), QPointF(size * 0.82, y2))
    p.drawLine(QPointF(size * 0.18, y3), QPointF(size * 0.82, y3))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(_color("#63d2ff"))
    p.drawEllipse(QRectF(size * 0.36, y1 - size * 0.07, size * 0.14, size * 0.14))
    p.drawEllipse(QRectF(size * 0.56, y2 - size * 0.07, size * 0.14, size * 0.14))
    p.drawEllipse(QRectF(size * 0.28, y3 - size * 0.07, size * 0.14, size * 0.14))


def _draw_recordings(p: QPainter, size: int) -> None:
    frame = QRectF(size * 0.16, size * 0.18, size * 0.68, size * 0.64)
    p.setPen(QPen(_color("#9cc9ef"), 1.2))
    p.setBrush(_color("#28496a"))
    p.drawRoundedRect(frame, size * 0.05, size * 0.05)

    p.setPen(QPen(_color("#5ea9dd"), 1))
    for i in range(3):
        x = size * (0.2 + i * 0.22)
        p.drawLine(QPointF(x, size * 0.22), QPointF(x, size * 0.78))

    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(_color("#5fd7ff"))
    play = QPainterPath()
    play.moveTo(size * 0.47, size * 0.39)
    play.lineTo(size * 0.47, size * 0.61)
    play.lineTo(size * 0.63, size * 0.5)
    play.closeSubpath()
    p.drawPath(play)


def _draw_temp(p: QPainter, size: int) -> None:
    p.setPen(QPen(_color("#9ec7f0"), 1.2))
    p.setBrush(_color("#2e4c6b"))
    p.drawRoundedRect(QRectF(size * 0.2, size * 0.54, size * 0.56, size * 0.2), size * 0.03, size * 0.03)
    p.setBrush(_color("#3f658c"))
    p.drawRoundedRect(QRectF(size * 0.24, size * 0.38, size * 0.56, size * 0.2), size * 0.03, size * 0.03)
    p.setBrush(_color("#5b8ec2"))
    p.drawRoundedRect(QRectF(size * 0.28, size * 0.22, size * 0.56, size * 0.2), size * 0.03, size * 0.03)


def _draw_ffmpeg(p: QPainter, size: int) -> None:
    chip = QRectF(size * 0.2, size * 0.2, size * 0.6, size * 0.6)
    p.setPen(QPen(_color("#9ec7f0"), 1.2))
    p.setBrush(_color("#233f5b"))
    p.drawRoundedRect(chip, size * 0.07, size * 0.07)

    p.setPen(QPen(_color("#73d7ff"), 1.2))
    for i in range(4):
        x = size * (0.25 + i * 0.16)
        p.drawLine(QPointF(x, size * 0.13), QPointF(x, size * 0.2))
        p.drawLine(QPointF(x, size * 0.8), QPointF(x, size * 0.87))
    for i in range(4):
        y = size * (0.25 + i * 0.16)
        p.drawLine(QPointF(size * 0.13, y), QPointF(size * 0.2, y))
        p.drawLine(QPointF(size * 0.8, y), QPointF(size * 0.87, y))

    p.setPen(_color("#d8f1ff"))
    font = QFont()
    font.setPixelSize(max(7, int(size * 0.24)))
    font.setBold(True)
    p.setFont(font)
    p.drawText(chip, Qt.AlignmentFlag.AlignCenter, "FF")


def _draw_mic(p: QPainter, size: int) -> None:
    p.setPen(QPen(_color("#9ec7f0"), 1.4))
    p.setBrush(_color("#3d6e9a"))
    capsule = QRectF(size * 0.36, size * 0.2, size * 0.28, size * 0.36)
    p.drawRoundedRect(capsule, size * 0.14, size * 0.14)

    p.setPen(QPen(_color("#d7e9ff"), 1.4))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawArc(QRectF(size * 0.28, size * 0.34, size * 0.44, size * 0.34), 200 * 16, 140 * 16)
    p.drawLine(QPointF(size * 0.5, size * 0.58), QPointF(size * 0.5, size * 0.76))
    p.drawLine(QPointF(size * 0.39, size * 0.76), QPointF(size * 0.61, size * 0.76))


def _draw_capture_region(p: QPainter, size: int) -> None:
    p.setPen(QPen(_color("#74d8ff"), 1.7))
    _draw_crop_corners(p, QRectF(size * 0.18, size * 0.18, size * 0.64, size * 0.64))
    p.setPen(QPen(_color("#d7e9ff"), 1.5))
    p.drawRect(QRectF(size * 0.34, size * 0.34, size * 0.32, size * 0.32))


def _draw_home(p: QPainter, size: int) -> None:
    p.setPen(QPen(_color("#d7e9ff"), 1.5))
    p.setBrush(_color("#2d4f74"))
    body = QRectF(size * 0.3, size * 0.46, size * 0.4, size * 0.32)
    roof = QPainterPath()
    roof.moveTo(size * 0.22, size * 0.48)
    roof.lineTo(size * 0.5, size * 0.2)
    roof.lineTo(size * 0.78, size * 0.48)
    roof.closeSubpath()
    p.drawPath(roof)
    p.drawRoundedRect(body, size * 0.03, size * 0.03)
    p.setBrush(_color("#7ad8ff"))
    p.drawRect(QRectF(size * 0.46, size * 0.56, size * 0.08, size * 0.22))


def _draw_general(p: QPainter, size: int) -> None:
    p.setPen(QPen(_color("#d7e9ff"), 1.4))
    p.setBrush(_color("#385f87"))
    p.drawEllipse(QRectF(size * 0.24, size * 0.24, size * 0.52, size * 0.52))
    for i in range(8):
        angle = i * 45
        p.save()
        p.translate(size * 0.5, size * 0.5)
        p.rotate(angle)
        p.drawLine(QPointF(size * 0.0, -size * 0.34), QPointF(size * 0.0, -size * 0.25))
        p.restore()
    p.setBrush(_color("#10253b"))
    p.drawEllipse(QRectF(size * 0.4, size * 0.4, size * 0.2, size * 0.2))


def _draw_video(p: QPainter, size: int) -> None:
    p.setPen(QPen(_color("#d7e9ff"), 1.4))
    p.setBrush(_color("#2d4f74"))
    body = QRectF(size * 0.2, size * 0.3, size * 0.5, size * 0.4)
    lens = QPainterPath()
    lens.moveTo(size * 0.7, size * 0.4)
    lens.lineTo(size * 0.86, size * 0.33)
    lens.lineTo(size * 0.86, size * 0.67)
    lens.lineTo(size * 0.7, size * 0.6)
    lens.closeSubpath()
    p.drawRoundedRect(body, size * 0.05, size * 0.05)
    p.drawPath(lens)
    p.setBrush(_color("#6fd6ff"))
    p.drawEllipse(QRectF(size * 0.34, size * 0.4, size * 0.18, size * 0.18))


def _draw_image(p: QPainter, size: int) -> None:
    p.setPen(QPen(_color("#d7e9ff"), 1.4))
    p.setBrush(_color("#2d4f74"))
    frame = QRectF(size * 0.18, size * 0.24, size * 0.64, size * 0.52)
    p.drawRoundedRect(frame, size * 0.05, size * 0.05)
    p.setPen(QPen(_color("#7ad8ff"), 1.4))
    p.drawLine(QPointF(size * 0.24, size * 0.66), QPointF(size * 0.42, size * 0.48))
    p.drawLine(QPointF(size * 0.42, size * 0.48), QPointF(size * 0.54, size * 0.58))
    p.drawLine(QPointF(size * 0.54, size * 0.58), QPointF(size * 0.76, size * 0.4))
    p.setBrush(_color("#7ad8ff"))
    p.drawEllipse(QRectF(size * 0.28, size * 0.32, size * 0.1, size * 0.1))


def _draw_about(p: QPainter, size: int) -> None:
    p.setPen(QPen(_color("#d7e9ff"), 1.4))
    p.setBrush(_color("#2d4f74"))
    p.drawEllipse(QRectF(size * 0.2, size * 0.2, size * 0.6, size * 0.6))
    p.setPen(_color("#7ad8ff"))
    font = QFont()
    font.setPixelSize(max(8, int(size * 0.44)))
    font.setBold(True)
    p.setFont(font)
    p.drawText(QRectF(size * 0.2, size * 0.2, size * 0.6, size * 0.6), Qt.AlignmentFlag.AlignCenter, "i")


def _draw_fullscreen(p: QPainter, size: int) -> None:
    p.setPen(QPen(_color("#d7e9ff"), 1.7))
    _draw_crop_corners(p, QRectF(size * 0.18, size * 0.18, size * 0.64, size * 0.64))


def _draw_window(p: QPainter, size: int) -> None:
    p.setPen(QPen(_color("#d7e9ff"), 1.4))
    p.setBrush(_color("#2d4f74"))
    outer = QRectF(size * 0.18, size * 0.2, size * 0.64, size * 0.58)
    p.drawRoundedRect(outer, size * 0.05, size * 0.05)
    p.setPen(QPen(_color("#7ad8ff"), 1.1))
    p.drawLine(QPointF(size * 0.22, size * 0.34), QPointF(size * 0.78, size * 0.34))
    p.drawLine(QPointF(size * 0.42, size * 0.34), QPointF(size * 0.42, size * 0.78))


def _draw_device(p: QPainter, size: int) -> None:
    p.setPen(QPen(_color("#d7e9ff"), 1.4))
    p.setBrush(_color("#2d4f74"))
    p.drawRoundedRect(QRectF(size * 0.2, size * 0.28, size * 0.6, size * 0.26), size * 0.06, size * 0.06)
    p.drawRoundedRect(QRectF(size * 0.3, size * 0.58, size * 0.4, size * 0.18), size * 0.05, size * 0.05)
    p.setBrush(_color("#7ad8ff"))
    p.drawEllipse(QRectF(size * 0.26, size * 0.34, size * 0.08, size * 0.08))
    p.drawEllipse(QRectF(size * 0.66, size * 0.34, size * 0.08, size * 0.08))


def _draw_game(p: QPainter, size: int) -> None:
    p.setPen(QPen(_color("#d7e9ff"), 1.4))
    p.setBrush(_color("#2d4f74"))
    pad = QRectF(size * 0.16, size * 0.34, size * 0.68, size * 0.34)
    p.drawRoundedRect(pad, size * 0.16, size * 0.16)
    p.setPen(QPen(_color("#7ad8ff"), 1.2))
    p.drawLine(QPointF(size * 0.3, size * 0.5), QPointF(size * 0.42, size * 0.5))
    p.drawLine(QPointF(size * 0.36, size * 0.44), QPointF(size * 0.36, size * 0.56))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(_color("#7ad8ff"))
    p.drawEllipse(QRectF(size * 0.58, size * 0.45, size * 0.07, size * 0.07))
    p.drawEllipse(QRectF(size * 0.68, size * 0.5, size * 0.07, size * 0.07))


def _draw_audio(p: QPainter, size: int) -> None:
    p.setPen(QPen(_color("#d7e9ff"), 1.4))
    p.setBrush(_color("#2d4f74"))
    cone = QPainterPath()
    cone.moveTo(size * 0.2, size * 0.56)
    cone.lineTo(size * 0.32, size * 0.56)
    cone.lineTo(size * 0.48, size * 0.68)
    cone.lineTo(size * 0.48, size * 0.32)
    cone.lineTo(size * 0.32, size * 0.44)
    cone.lineTo(size * 0.2, size * 0.44)
    cone.closeSubpath()
    p.drawPath(cone)
    p.setPen(QPen(_color("#7ad8ff"), 1.4))
    p.drawArc(QRectF(size * 0.46, size * 0.34, size * 0.24, size * 0.32), -35 * 16, 70 * 16)
    p.drawArc(QRectF(size * 0.52, size * 0.28, size * 0.3, size * 0.44), -35 * 16, 70 * 16)


def _draw_screenshot(p: QPainter, size: int) -> None:
    p.setPen(QPen(_color("#d7e9ff"), 1.4))
    p.setBrush(_color("#2d4f74"))
    body = QRectF(size * 0.18, size * 0.3, size * 0.64, size * 0.44)
    p.drawRoundedRect(body, size * 0.07, size * 0.07)

    p.setBrush(_color("#3f79af"))
    top = QRectF(size * 0.34, size * 0.22, size * 0.24, size * 0.12)
    p.drawRoundedRect(top, size * 0.03, size * 0.03)

    p.setPen(QPen(_color("#7ad8ff"), 1.3))
    p.setBrush(_color("#3f79af"))
    p.drawEllipse(QRectF(size * 0.36, size * 0.4, size * 0.28, size * 0.28))

    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(_color("#7ad8ff"))
    p.drawEllipse(QRectF(size * 0.45, size * 0.49, size * 0.1, size * 0.1))


def _draw_crop_corners(p: QPainter, rect: QRectF) -> None:
    left = rect.left()
    top = rect.top()
    right = rect.right()
    bottom = rect.bottom()
    arm = min(rect.width(), rect.height()) * 0.24

    p.drawLine(QPointF(left, top), QPointF(left + arm, top))
    p.drawLine(QPointF(left, top), QPointF(left, top + arm))

    p.drawLine(QPointF(right, top), QPointF(right - arm, top))
    p.drawLine(QPointF(right, top), QPointF(right, top + arm))

    p.drawLine(QPointF(left, bottom), QPointF(left + arm, bottom))
    p.drawLine(QPointF(left, bottom), QPointF(left, bottom - arm))

    p.drawLine(QPointF(right, bottom), QPointF(right - arm, bottom))
    p.drawLine(QPointF(right, bottom), QPointF(right, bottom - arm))
