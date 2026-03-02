from __future__ import annotations

import ctypes
import sys

from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtGui import QColor, QCursor, QKeyEvent, QMouseEvent, QPainter, QPen
from PySide6.QtWidgets import QApplication, QDialog, QWidget

from app.core.recorder import CaptureRegion


class RegionSelectionOverlay(QDialog):
    def __init__(self, parent: QWidget | None, screen) -> None:
        super().__init__(parent)
        self._screen = screen
        self._start: QPoint | None = None
        self._current: QPoint | None = None
        self._selection = QRect()
        self._selected_region: CaptureRegion | None = None

        self._scale_x = float(screen.devicePixelRatio())
        self._scale_y = float(screen.devicePixelRatio())
        self._origin_x = int(round(screen.geometry().x() * self._scale_x))
        self._origin_y = int(round(screen.geometry().y() * self._scale_y))

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setModal(True)
        self.setGeometry(screen.geometry())
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)

    @property
    def selected_region(self) -> CaptureRegion | None:
        return self._selected_region

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._update_win32_metrics()
        self.activateWindow()
        self.raise_()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.reject()
            return
        super().keyPressEvent(event)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.RightButton:
            self.reject()
            return

        if event.button() != Qt.MouseButton.LeftButton:
            return

        point = event.position().toPoint()
        self._start = point
        self._current = point
        self._selection = QRect(point, point)
        self.update()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._start is None:
            return
        self._current = event.position().toPoint()
        self._selection = QRect(self._start, self._current).normalized()
        self.update()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() != Qt.MouseButton.LeftButton or self._start is None:
            return

        self._current = event.position().toPoint()
        self._selection = QRect(self._start, self._current).normalized()
        if self._selection.width() < 6 or self._selection.height() < 6:
            self._selection = QRect()
            self._start = None
            self._current = None
            self.update()
            return

        self._selected_region = self._to_physical_region(self._selection)
        self.accept()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        painter.fillRect(self.rect(), QColor(5, 10, 18, 155))
        self._draw_instruction_badge(painter)

        if self._selection.isNull():
            return

        selection = self._selection.normalized()

        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
        painter.fillRect(selection, Qt.GlobalColor.transparent)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)

        painter.setPen(QPen(QColor(79, 205, 255), 2))
        painter.drawRect(selection.adjusted(0, 0, -1, -1))
        self._draw_size_badge(painter, selection)

    def _draw_instruction_badge(self, painter: QPainter) -> None:
        text = "Drag to select capture region. Release to confirm. Esc or right-click to cancel."
        metrics = painter.fontMetrics()
        width = metrics.horizontalAdvance(text) + 28
        height = metrics.height() + 16
        x = (self.width() - width) // 2
        y = 18
        badge = QRect(x, y, width, height)

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(18, 32, 48, 215))
        painter.drawRoundedRect(badge, 10, 10)
        painter.setPen(QColor(224, 242, 255))
        painter.drawText(badge, Qt.AlignmentFlag.AlignCenter, text)

    def _draw_size_badge(self, painter: QPainter, selection: QRect) -> None:
        width_px = int(round(selection.width() * self._scale_x))
        height_px = int(round(selection.height() * self._scale_y))
        text = f"{width_px} x {height_px}px"

        metrics = painter.fontMetrics()
        badge_w = metrics.horizontalAdvance(text) + 16
        badge_h = metrics.height() + 10
        x = selection.left()
        y = selection.top() - badge_h - 8
        if y < 8:
            y = selection.bottom() + 8

        badge = QRect(x, y, badge_w, badge_h)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(28, 49, 74, 220))
        painter.drawRoundedRect(badge, 8, 8)
        painter.setPen(QColor(231, 246, 255))
        painter.drawText(badge, Qt.AlignmentFlag.AlignCenter, text)

    def _to_physical_region(self, logical_rect: QRect) -> CaptureRegion:
        x = self._origin_x + int(round(logical_rect.x() * self._scale_x))
        y = self._origin_y + int(round(logical_rect.y() * self._scale_y))
        width = max(2, int(round(logical_rect.width() * self._scale_x)))
        height = max(2, int(round(logical_rect.height() * self._scale_y)))
        return CaptureRegion(x=x, y=y, width=width, height=height)

    def _update_win32_metrics(self) -> None:
        if sys.platform != "win32":
            return

        try:
            user32 = ctypes.windll.user32

            class RECT(ctypes.Structure):
                _fields_ = [
                    ("left", ctypes.c_long),
                    ("top", ctypes.c_long),
                    ("right", ctypes.c_long),
                    ("bottom", ctypes.c_long),
                ]

            class MONITORINFO(ctypes.Structure):
                _fields_ = [
                    ("cbSize", ctypes.c_ulong),
                    ("rcMonitor", RECT),
                    ("rcWork", RECT),
                    ("dwFlags", ctypes.c_ulong),
                ]

            monitor_default_to_nearest = 2
            hwnd = int(self.winId())
            hmonitor = user32.MonitorFromWindow(hwnd, monitor_default_to_nearest)
            if not hmonitor:
                return

            info = MONITORINFO()
            info.cbSize = ctypes.sizeof(MONITORINFO)
            ok = user32.GetMonitorInfoW(hmonitor, ctypes.byref(info))
            if not ok:
                return

            monitor_width = info.rcMonitor.right - info.rcMonitor.left
            monitor_height = info.rcMonitor.bottom - info.rcMonitor.top
            if self.width() <= 0 or self.height() <= 0:
                return
            if monitor_width <= 0 or monitor_height <= 0:
                return

            self._scale_x = monitor_width / float(self.width())
            self._scale_y = monitor_height / float(self.height())
            self._origin_x = int(info.rcMonitor.left)
            self._origin_y = int(info.rcMonitor.top)
        except Exception:
            return


def select_region(parent: QWidget | None = None) -> CaptureRegion | None:
    app = QApplication.instance()
    if app is None:
        return None

    cursor_pos = QCursor.pos()
    screen = app.screenAt(cursor_pos) or app.primaryScreen()
    if screen is None:
        return None

    overlay = RegionSelectionOverlay(parent=parent, screen=screen)
    result = overlay.exec()
    if result == QDialog.DialogCode.Accepted:
        return overlay.selected_region
    return None
