from __future__ import annotations

from datetime import datetime
import os
import platform
from pathlib import Path
import re
import subprocess
import sys
import time
from typing import Callable

from PySide6.QtCore import QRect, QSize, Qt, QTimer
from PySide6.QtGui import QGuiApplication
from PySide6.QtMultimedia import QCamera, QCameraDevice, QMediaCaptureSession, QMediaDevices
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.core.ffmpeg import detect_ffmpeg
from app.core.paths import get_app_paths, set_recordings_dir
from app.core.recorder import (
    CaptureRegion,
    H264EncoderSupport,
    RecorderController,
    RecordingLibraryItem,
    RecoverySession,
    WebcamInputError,
    WebcamOverlay,
)
from app.core.win_devices import (
    DeviceLists,
    SystemAudioDevice,
    list_dshow_devices,
    pick_default_mic,
    pick_default_system_audio,
    pick_default_webcam,
    supports_wasapi_loopback,
)
from app.core.win_windows import get_foreground_window_title, list_visible_window_titles
from app.ui.icon_factory import build_app_icon, build_icon
from app.ui.region_selector import select_region


class WebcamPreviewOverlay(QWidget):
    def __init__(self) -> None:
        super().__init__(
            None,
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.WindowDoesNotAcceptFocus,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setWindowTitle("CAPTRIX Webcam Preview")

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        frame = QFrame()
        frame.setObjectName("WebcamPreviewFrame")
        self._content_layout = QVBoxLayout(frame)
        self._content_layout.setContentsMargins(2, 2, 2, 2)
        self._content_layout.setSpacing(0)

        self.video_widget = QVideoWidget()
        self.placeholder_label = QLabel("WEBCAM OVERLAY")
        self.placeholder_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.placeholder_label.setObjectName("WebcamPreviewPlaceholder")
        self._content_layout.addWidget(self.video_widget)
        root.addWidget(frame)

        self.setStyleSheet(
            """
            QFrame#WebcamPreviewFrame {
                background-color: #0f1218;
                border: 2px solid #e8f1ff;
                border-radius: 10px;
            }
            QLabel#WebcamPreviewPlaceholder {
                color: #f2f7ff;
                font-weight: 700;
                font-size: 12pt;
                background-color: #121821;
            }
            """
        )

        self.capture_session = QMediaCaptureSession(self)
        self.capture_session.setVideoOutput(self.video_widget)
        self.camera: QCamera | None = None
        self.current_device_description: str | None = None

    def _set_content_widget(self, widget: QWidget) -> None:
        while self._content_layout.count() > 0:
            item = self._content_layout.takeAt(0)
            child = item.widget()
            if child is not None:
                child.hide()
                child.setParent(None)
        self._content_layout.addWidget(widget)
        widget.show()

    @staticmethod
    def _normalize(text: str) -> str:
        return re.sub(r"[^a-z0-9]+", "", text.lower())

    def _find_camera_device(self, requested_name: str) -> QCameraDevice | None:
        devices = list(QMediaDevices.videoInputs())
        if not devices:
            return None

        exact_lower = requested_name.lower()
        for device in devices:
            if device.description().lower() == exact_lower:
                return device

        wanted = self._normalize(requested_name)
        for device in devices:
            desc = self._normalize(device.description())
            if wanted and (wanted in desc or desc in wanted):
                return device

        return devices[0]

    def start_preview(self, requested_name: str) -> bool:
        target = self._find_camera_device(requested_name)
        if target is None:
            self.stop_preview()
            return False

        if (
            self.camera is not None
            and self.current_device_description is not None
            and self.current_device_description.lower() == target.description().lower()
        ):
            self._set_content_widget(self.video_widget)
            self.capture_session.setVideoOutput(self.video_widget)
            if not self.isVisible():
                self.show()
            return True

        self.stop_preview()
        self._set_content_widget(self.video_widget)
        self.camera = QCamera(target)
        self.capture_session.setVideoOutput(self.video_widget)
        self.capture_session.setCamera(self.camera)
        self.camera.start()
        self.current_device_description = target.description()
        self.show()
        return True

    def show_placeholder(self, text: str = "WEBCAM OVERLAY") -> None:
        self.stop_preview(hide_window=False)
        self.capture_session.setVideoOutput(None)
        self.placeholder_label.setText(text)
        self._set_content_widget(self.placeholder_label)
        self.show()

    def stop_preview(self, hide_window: bool = True) -> None:
        if self.camera is not None:
            try:
                self.camera.stop()
            except Exception:
                pass
            self.capture_session.setCamera(None)
            self.camera.deleteLater()
            self.camera = None
        self.current_device_description = None
        if self.video_widget.parent() is not None:
            self.video_widget.hide()
        if hide_window:
            self.hide()

    def update_geometry_for_overlay(self, screen_rect: QRect, size_percent: int, position: str, margin: int = 24) -> None:
        if not screen_rect.isValid():
            return

        size = max(16, min(70, int(size_percent)))
        short_side = min(screen_rect.width(), screen_rect.height())
        width = max(180, int(short_side * size / 100))
        height = max(110, int(width * 9 / 16))

        max_height = int(screen_rect.height() * 0.45)
        if height > max_height:
            height = max(110, max_height)
            width = int(height * 16 / 9)

        if position == "top_left":
            x = screen_rect.left() + margin
            y = screen_rect.top() + margin
        elif position == "top_right":
            x = screen_rect.right() - width - margin
            y = screen_rect.top() + margin
        elif position == "bottom_left":
            x = screen_rect.left() + margin
            y = screen_rect.bottom() - height - margin
        else:
            x = screen_rect.right() - width - margin
            y = screen_rect.bottom() - height - margin

        self.setGeometry(x, y, width, height)


class MainWindow(QMainWindow):
    ALL_MODES = ("region", "fullscreen", "window", "device", "game", "audio")
    WEBCAM_POSITIONS = {
        "Top-Left": "top_left",
        "Top-Right": "top_right",
        "Bottom-Left": "bottom_left",
        "Bottom-Right": "bottom_right",
    }
    ENCODER_OPTIONS = {
        "Auto (Best Available)": "auto",
    }
    QUALITY_OPTIONS = {
        "Balanced": "balanced",
        "High Quality": "high_quality",
        "Small File": "small_file",
    }

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("CAPTRIX")
        self.setMinimumSize(1080, 680)
        self.setWindowIcon(build_app_icon(24))

        self.paths = get_app_paths("CAPTRIX")
        self.ff = detect_ffmpeg()
        self.recorder: RecorderController | None = None

        self.current_mode = "region"
        self.region_mode = "crop"

        self.device_lists: DeviceLists | None = None
        self.mic_name: str | None = None
        self.selected_region: CaptureRegion | None = None
        self.selected_window_title: str | None = None
        self.selected_game_window_title: str | None = None
        self.selected_device_video: str | None = None
        self.selected_device_audio: str | None = None
        self.selected_audio_source: str | None = None
        self.webcam_enabled: bool = False
        self.selected_webcam_device: str | None = None
        self.webcam_size_percent: int = 32
        self.webcam_position: str = "bottom_right"
        self.system_audio_enabled: bool = False
        self.system_audio_devices: list[SystemAudioDevice] = []
        self.selected_system_audio_device: SystemAudioDevice | None = None
        self.system_audio_wasapi_supported: bool = False
        self.mic_volume_percent: int = 100
        self.system_audio_volume_percent: int = 100
        self.video_encoder_preference: str = "auto"
        self.video_quality_preset: str = "balanced"
        self.h264_encoder_support: H264EncoderSupport | None = None

        self.mode_tiles: dict[str, QPushButton] = {}
        self.toolbar_mode_buttons: dict[str, QPushButton] = {}
        self.nav_buttons: dict[str, QPushButton] = {}
        self.home_tab_buttons: dict[str, QPushButton] = {}
        self.home_tab_indices: dict[str, int] = {}
        self.current_home_tab: str = "get_started"
        self.library_meta_labels: dict[str, QLabel] = {}
        self.library_search_inputs: dict[str, QLineEdit] = {}
        self.library_tables: dict[str, QTableWidget] = {}
        self.library_rows: dict[str, list[RecordingLibraryItem]] = {}
        self.library_open_buttons: dict[str, QPushButton] = {}
        self.library_rename_buttons: dict[str, QPushButton] = {}
        self.library_delete_buttons: dict[str, QPushButton] = {}
        self.library_reveal_buttons: dict[str, QPushButton] = {}
        self.current_section: str = "home"
        self._section_primary_handler: Callable[[], None] | None = None
        self._section_secondary_handler: Callable[[], None] | None = None
        self.webcam_preview_overlay = WebcamPreviewOverlay()
        self._webcam_preview_error_shown = False

        self._build_ui()
        self._apply_theme()
        self._set_capture_mode("region", announce=False)
        self._set_sidebar_section("home")
        self._set_status_chip("busy", "Initializing")
        self.refresh_status()
        QTimer.singleShot(250, self._check_recovery_sessions_on_startup)

    def _build_ui(self) -> None:
        root = QWidget()
        root.setObjectName("Root")
        self.setCentralWidget(root)

        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        top_bar = QFrame()
        top_bar.setObjectName("TopBar")
        top_bar.setFixedHeight(86)
        top_layout = QHBoxLayout(top_bar)
        top_layout.setContentsMargins(20, 14, 20, 14)
        top_layout.setSpacing(12)

        brand_icon = QLabel()
        brand_icon.setPixmap(build_app_icon(28).pixmap(28, 28))
        brand_icon.setFixedSize(30, 30)
        brand_icon.setAlignment(Qt.AlignCenter)

        brand_text = QLabel("CAPTRIX")
        brand_text.setObjectName("BrandTitle")

        top_layout.addWidget(brand_icon)
        top_layout.addWidget(brand_text)
        top_layout.addSpacing(18)

        mode_buttons = [
            ("region", "Rectangle Area", "region"),
            ("fullscreen", "Fullscreen", "fullscreen"),
            ("window", "Specific Window", "window"),
            ("device", "Device Recording", "device"),
            ("game", "Game Recording", "game"),
            ("audio", "Audio Only", "audio"),
        ]
        for mode_key, tip, icon_name in mode_buttons:
            button = self._create_toolbar_button(mode_key, tip, icon_name)
            self.toolbar_mode_buttons[mode_key] = button
            top_layout.addWidget(button)

        top_layout.addStretch(1)

        self.status_chip = QLabel("Initializing")
        self.status_chip.setObjectName("StatusChip")
        self.status_chip.setAlignment(Qt.AlignCenter)
        self.status_chip.setMinimumWidth(150)

        self.change_recordings_button = QPushButton("Output Folder")
        self.change_recordings_button.setObjectName("TopSecondaryButton")
        self.change_recordings_button.setIcon(build_icon("folder", 14))
        self.change_recordings_button.clicked.connect(self.on_change_recordings_clicked)

        self.screenshot_button = QPushButton("SHOT")
        self.screenshot_button.setObjectName("TopShotButton")
        self.screenshot_button.setIcon(build_icon("screenshot", 14))
        self.screenshot_button.clicked.connect(self.on_take_screenshot_clicked)

        self.record_button = QPushButton("REC")
        self.record_button.setObjectName("TopRecordButton")
        self.record_button.setIcon(build_icon("play", 14))
        self.record_button.clicked.connect(self.on_start_recording_clicked)

        self.stop_button = QPushButton("STOP")
        self.stop_button.setObjectName("TopStopButton")
        self.stop_button.setIcon(build_icon("stop", 14))
        self.stop_button.clicked.connect(self.on_stop_recording_clicked)
        self.stop_button.setEnabled(False)

        self.rec_indicator = QLabel()
        self.rec_indicator.setObjectName("RecIndicator")
        self.rec_indicator.setFixedSize(34, 34)
        self.rec_indicator.setAlignment(Qt.AlignCenter)
        self.rec_indicator.setPixmap(build_icon("rec", 24).pixmap(24, 24))

        top_layout.addWidget(self.status_chip)
        top_layout.addWidget(self.change_recordings_button)
        top_layout.addWidget(self.screenshot_button)
        top_layout.addWidget(self.record_button)
        top_layout.addWidget(self.stop_button)
        top_layout.addWidget(self.rec_indicator)
        root_layout.addWidget(top_bar)

        hint_bar = QFrame()
        hint_bar.setObjectName("HintBar")
        hint_layout = QHBoxLayout(hint_bar)
        hint_layout.setContentsMargins(16, 8, 16, 8)
        hint_layout.setSpacing(10)

        hint_icon = QLabel()
        hint_icon.setPixmap(build_icon("region", 14).pixmap(14, 14))
        hint_icon.setFixedSize(16, 16)
        self.hint_label = QLabel("Please select a recording mode")
        self.hint_label.setObjectName("HintLabel")
        hint_layout.addWidget(hint_icon)
        hint_layout.addWidget(self.hint_label)
        hint_layout.addStretch(1)
        self.output_hint_label = QLabel("")
        self.output_hint_label.setObjectName("OutputHintLabel")
        self.output_hint_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        hint_layout.addWidget(self.output_hint_label)
        root_layout.addWidget(hint_bar)

        center = QFrame()
        center.setObjectName("CenterFrame")
        center_layout = QHBoxLayout(center)
        center_layout.setContentsMargins(14, 14, 14, 14)
        center_layout.setSpacing(14)
        root_layout.addWidget(center, 1)

        self._build_sidebar(center_layout)
        self._build_workspace(center_layout)

    def _build_sidebar(self, parent_layout: QHBoxLayout) -> None:
        sidebar = QFrame()
        sidebar.setObjectName("Sidebar")
        sidebar.setFixedWidth(190)
        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(14, 16, 14, 16)
        layout.setSpacing(8)
        nav_items = [
            ("home", "Home", "home", True),
            ("general", "General", "general", False),
            ("video", "Video", "video", False),
            ("image", "Image", "image", False),
            ("about", "About", "about", False),
        ]
        for section_key, text, icon, active in nav_items:
            button = self._create_nav_button(section_key, text, icon, active)
            self.nav_buttons[section_key] = button
            layout.addWidget(button)
        layout.addStretch(1)
        footer = QLabel("CAPTRIX")
        footer.setObjectName("SidebarFooter")
        footer.setAlignment(Qt.AlignCenter)
        layout.addWidget(footer)
        parent_layout.addWidget(sidebar)

    def _build_workspace(self, parent_layout: QHBoxLayout) -> None:
        workspace = QFrame()
        workspace.setObjectName("Workspace")
        layout = QVBoxLayout(workspace)
        layout.setContentsMargins(22, 20, 22, 20)
        layout.setSpacing(16)

        self.home_panel = QWidget()
        home_layout = QVBoxLayout(self.home_panel)
        home_layout.setContentsMargins(0, 0, 0, 0)
        home_layout.setSpacing(16)

        tabs_row = QHBoxLayout()
        tabs_row.setSpacing(22)
        home_tabs = [
            ("get_started", "Get Started"),
            ("videos", "Videos"),
            ("images", "Images"),
            ("audios", "Audios"),
        ]
        for tab_key, text in home_tabs:
            button = self._create_home_tab_button(tab_key, text, active=(tab_key == "get_started"))
            self.home_tab_buttons[tab_key] = button
            tabs_row.addWidget(button)
        tabs_row.addStretch(1)
        home_layout.addLayout(tabs_row)

        self.home_stack = QStackedWidget()
        self.home_stack.setObjectName("HomeStack")

        get_started_page = QWidget()
        get_started_layout = QVBoxLayout(get_started_page)
        get_started_layout.setContentsMargins(0, 0, 0, 0)
        get_started_layout.setSpacing(16)

        mode_grid = QGridLayout()
        mode_grid.setHorizontalSpacing(14)
        mode_grid.setVerticalSpacing(14)
        mode_grid.setColumnStretch(0, 1)
        mode_grid.setColumnStretch(1, 1)
        mode_grid.setColumnStretch(2, 1)

        tiles = [
            ("region", "Rectangle area", "Choose partial area", "region"),
            ("fullscreen", "Fullscreen", "Capture all displays", "fullscreen"),
            ("window", "Specific window", "Target one window", "window"),
            ("device", "Device recording", "Capture from camera/card", "device"),
            ("game", "Game recording", "Target game window", "game"),
            ("audio", "Audio only", "Record audio source", "audio"),
        ]
        for mode_key, title, subtitle, icon_name in tiles:
            self.mode_tiles[mode_key] = self._create_mode_tile(mode_key, title, subtitle, icon_name)

        mode_grid.addWidget(self.mode_tiles["region"], 0, 0)
        mode_grid.addWidget(self.mode_tiles["fullscreen"], 0, 1)
        mode_grid.addWidget(self.mode_tiles["window"], 0, 2)
        mode_grid.addWidget(self.mode_tiles["device"], 1, 0)
        mode_grid.addWidget(self.mode_tiles["game"], 1, 1)
        mode_grid.addWidget(self.mode_tiles["audio"], 1, 2)
        get_started_layout.addLayout(mode_grid)

        self.mode_description_label = QLabel("Screen Recording - Rectangle area mode captures only your selected region.")
        self.mode_description_label.setObjectName("ModeDescription")
        self.mode_description_label.setWordWrap(True)
        get_started_layout.addWidget(self.mode_description_label)

        self.video_encoding_panel = QFrame()
        self.video_encoding_panel.setObjectName("VideoEncodePanel")
        video_layout = QGridLayout(self.video_encoding_panel)
        self._configure_form_panel_layout(video_layout)

        encoder_label = QLabel("Encoder (Auto)")
        encoder_label.setObjectName("VideoLabel")
        encoder_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.encoder_combo = QComboBox()
        self.encoder_combo.setObjectName("VideoCombo")
        self.encoder_combo.setMinimumHeight(30)
        self.encoder_combo.addItems(list(self.ENCODER_OPTIONS.keys()))
        self.encoder_combo.setCurrentText("Auto (Best Available)")
        self.encoder_combo.currentTextChanged.connect(self.on_encoder_changed)
        self.encoder_combo.setEnabled(False)
        self.encoder_combo.setToolTip("Encoder is auto-assigned based on detected hardware and FFmpeg support.")
        video_layout.addWidget(encoder_label, 0, 0)
        video_layout.addWidget(self.encoder_combo, 0, 1, 1, 2)

        quality_label = QLabel("Quality Preset")
        quality_label.setObjectName("VideoLabel")
        quality_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.quality_combo = QComboBox()
        self.quality_combo.setObjectName("VideoCombo")
        self.quality_combo.setMinimumHeight(30)
        self.quality_combo.addItems(list(self.QUALITY_OPTIONS.keys()))
        self.quality_combo.setCurrentText("Balanced")
        self.quality_combo.currentTextChanged.connect(self.on_quality_changed)
        video_layout.addWidget(quality_label, 1, 0)
        video_layout.addWidget(self.quality_combo, 1, 1, 1, 2)

        self.video_encoding_hint_label = QLabel("")
        self.video_encoding_hint_label.setObjectName("VideoHint")
        self.video_encoding_hint_label.setWordWrap(True)
        video_layout.addWidget(self.video_encoding_hint_label, 2, 0, 1, 3)
        get_started_layout.addWidget(self.video_encoding_panel)

        action_row = QHBoxLayout()
        action_row.setSpacing(10)

        self.select_region_button = QPushButton("Select Region")
        self.select_region_button.setObjectName("InlineButton")
        self.select_region_button.setIcon(build_icon("region", 14))
        self.select_region_button.clicked.connect(self.on_select_region_clicked)

        self.clear_region_button = QPushButton("Clear Region")
        self.clear_region_button.setObjectName("InlineButton")
        self.clear_region_button.setIcon(build_icon("clear", 14))
        self.clear_region_button.clicked.connect(self.on_clear_region_clicked)

        self.select_source_button = QPushButton("Select Source")
        self.select_source_button.setObjectName("InlineButton")
        self.select_source_button.setIcon(build_icon("video", 14))
        self.select_source_button.clicked.connect(self.on_select_source_clicked)

        self.clear_source_button = QPushButton("Clear Source")
        self.clear_source_button.setObjectName("InlineButton")
        self.clear_source_button.setIcon(build_icon("clear", 14))
        self.clear_source_button.clicked.connect(self.on_clear_source_clicked)

        self.sync_test_button = QPushButton("Sync Test")
        self.sync_test_button.setObjectName("InlineButton")
        self.sync_test_button.setIcon(build_icon("audio", 14))
        self.sync_test_button.clicked.connect(self.on_generate_sync_test_clicked)

        action_row.addWidget(self.select_region_button)
        action_row.addWidget(self.clear_region_button)
        action_row.addWidget(self.select_source_button)
        action_row.addWidget(self.clear_source_button)
        action_row.addWidget(self.sync_test_button)
        action_row.addStretch(1)
        get_started_layout.addLayout(action_row)

        self.webcam_panel = QFrame()
        self.webcam_panel.setObjectName("WebcamPanel")
        webcam_layout = QGridLayout(self.webcam_panel)
        self._configure_form_panel_layout(webcam_layout)

        self.webcam_enable_checkbox = QCheckBox("Enable Webcam Overlay (Picture-in-Picture)")
        self.webcam_enable_checkbox.setObjectName("WebcamToggle")
        self.webcam_enable_checkbox.toggled.connect(self.on_webcam_toggle_changed)
        webcam_layout.addWidget(self.webcam_enable_checkbox, 0, 0, 1, 3)

        webcam_device_label = QLabel("Webcam Device")
        webcam_device_label.setObjectName("WebcamLabel")
        webcam_device_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.webcam_device_combo = QComboBox()
        self.webcam_device_combo.setObjectName("WebcamCombo")
        self.webcam_device_combo.setMinimumHeight(30)
        self.webcam_device_combo.currentTextChanged.connect(self.on_webcam_device_changed)
        webcam_layout.addWidget(webcam_device_label, 1, 0)
        webcam_layout.addWidget(self.webcam_device_combo, 1, 1, 1, 2)

        webcam_size_label = QLabel("Size")
        webcam_size_label.setObjectName("WebcamLabel")
        webcam_size_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.webcam_size_slider = QSlider(Qt.Orientation.Horizontal)
        self.webcam_size_slider.setRange(16, 70)
        self.webcam_size_slider.setSingleStep(1)
        self.webcam_size_slider.setValue(self.webcam_size_percent)
        self.webcam_size_slider.setFixedHeight(24)
        self.webcam_size_slider.valueChanged.connect(self.on_webcam_size_changed)
        self.webcam_size_value_label = QLabel(f"{self.webcam_size_percent}%")
        self.webcam_size_value_label.setObjectName("WebcamValue")
        self.webcam_size_value_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        webcam_layout.addWidget(webcam_size_label, 2, 0)
        webcam_layout.addWidget(self.webcam_size_slider, 2, 1)
        webcam_layout.addWidget(self.webcam_size_value_label, 2, 2)

        webcam_pos_label = QLabel("Position")
        webcam_pos_label.setObjectName("WebcamLabel")
        webcam_pos_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.webcam_position_combo = QComboBox()
        self.webcam_position_combo.setObjectName("WebcamCombo")
        self.webcam_position_combo.setMinimumHeight(30)
        self.webcam_position_combo.addItems(list(self.WEBCAM_POSITIONS.keys()))
        self.webcam_position_combo.setCurrentText("Bottom-Right")
        self.webcam_position_combo.currentTextChanged.connect(self.on_webcam_position_changed)
        webcam_layout.addWidget(webcam_pos_label, 3, 0)
        webcam_layout.addWidget(self.webcam_position_combo, 3, 1, 1, 2)

        self.webcam_hint_label = QLabel("")
        self.webcam_hint_label.setObjectName("WebcamHint")
        self.webcam_hint_label.setWordWrap(True)
        webcam_layout.addWidget(self.webcam_hint_label, 4, 0, 1, 3)
        get_started_layout.addWidget(self.webcam_panel)

        self.audio_mix_panel = QFrame()
        self.audio_mix_panel.setObjectName("AudioMixPanel")
        audio_layout = QGridLayout(self.audio_mix_panel)
        self._configure_form_panel_layout(audio_layout)

        self.system_audio_enable_checkbox = QCheckBox("Enable System Audio (Desktop Sound)")
        self.system_audio_enable_checkbox.setObjectName("AudioToggle")
        self.system_audio_enable_checkbox.toggled.connect(self.on_system_audio_toggle_changed)
        audio_layout.addWidget(self.system_audio_enable_checkbox, 0, 0, 1, 3)

        system_device_label = QLabel("System Audio Device")
        system_device_label.setObjectName("AudioLabel")
        system_device_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.system_audio_device_combo = QComboBox()
        self.system_audio_device_combo.setObjectName("AudioCombo")
        self.system_audio_device_combo.setMinimumHeight(30)
        self.system_audio_device_combo.currentIndexChanged.connect(self.on_system_audio_device_changed)
        audio_layout.addWidget(system_device_label, 1, 0)
        audio_layout.addWidget(self.system_audio_device_combo, 1, 1, 1, 2)

        mic_volume_label = QLabel("Mic Volume")
        mic_volume_label.setObjectName("AudioLabel")
        mic_volume_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.mic_volume_slider = QSlider(Qt.Orientation.Horizontal)
        self.mic_volume_slider.setRange(0, 200)
        self.mic_volume_slider.setSingleStep(1)
        self.mic_volume_slider.setValue(self.mic_volume_percent)
        self.mic_volume_slider.setFixedHeight(24)
        self.mic_volume_slider.valueChanged.connect(self.on_mic_volume_changed)
        self.mic_volume_value_label = QLabel(f"{self.mic_volume_percent}%")
        self.mic_volume_value_label.setObjectName("AudioValue")
        self.mic_volume_value_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        audio_layout.addWidget(mic_volume_label, 2, 0)
        audio_layout.addWidget(self.mic_volume_slider, 2, 1)
        audio_layout.addWidget(self.mic_volume_value_label, 2, 2)

        system_volume_label = QLabel("System Volume")
        system_volume_label.setObjectName("AudioLabel")
        system_volume_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.system_audio_volume_slider = QSlider(Qt.Orientation.Horizontal)
        self.system_audio_volume_slider.setRange(0, 200)
        self.system_audio_volume_slider.setSingleStep(1)
        self.system_audio_volume_slider.setValue(self.system_audio_volume_percent)
        self.system_audio_volume_slider.setFixedHeight(24)
        self.system_audio_volume_slider.valueChanged.connect(self.on_system_audio_volume_changed)
        self.system_audio_volume_value_label = QLabel(f"{self.system_audio_volume_percent}%")
        self.system_audio_volume_value_label.setObjectName("AudioValue")
        self.system_audio_volume_value_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        audio_layout.addWidget(system_volume_label, 3, 0)
        audio_layout.addWidget(self.system_audio_volume_slider, 3, 1)
        audio_layout.addWidget(self.system_audio_volume_value_label, 3, 2)

        self.audio_mix_hint_label = QLabel("")
        self.audio_mix_hint_label.setObjectName("AudioHint")
        self.audio_mix_hint_label.setWordWrap(True)
        audio_layout.addWidget(self.audio_mix_hint_label, 4, 0, 1, 3)
        get_started_layout.addWidget(self.audio_mix_panel)

        get_started_layout.addStretch(1)

        get_started_scroll = QScrollArea()
        get_started_scroll.setObjectName("GetStartedScroll")
        get_started_scroll.setWidgetResizable(True)
        get_started_scroll.setFrameShape(QFrame.Shape.NoFrame)
        get_started_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        get_started_scroll.setWidget(get_started_page)

        self.home_tab_indices["get_started"] = self.home_stack.addWidget(get_started_scroll)
        self.home_tab_indices["videos"] = self.home_stack.addWidget(self._create_library_page("videos", "Videos"))
        self.home_tab_indices["images"] = self.home_stack.addWidget(self._create_library_page("images", "Images"))
        self.home_tab_indices["audios"] = self.home_stack.addWidget(self._create_library_page("audios", "Audios"))
        home_layout.addWidget(self.home_stack, 1)

        self.section_panel = QFrame()
        self.section_panel.setObjectName("SectionPanel")
        section_layout = QVBoxLayout(self.section_panel)
        section_layout.setContentsMargins(14, 12, 14, 12)
        section_layout.setSpacing(10)

        self.section_title_label = QLabel("Section")
        self.section_title_label.setObjectName("SectionTitle")
        section_layout.addWidget(self.section_title_label)

        self.section_body_label = QLabel("Use the sidebar to navigate between settings panels.")
        self.section_body_label.setObjectName("SectionBody")
        self.section_body_label.setWordWrap(True)
        section_layout.addWidget(self.section_body_label)

        section_actions = QHBoxLayout()
        section_actions.setSpacing(8)
        self.section_primary_button = QPushButton("Primary Action")
        self.section_primary_button.setObjectName("SectionAction")
        self.section_primary_button.clicked.connect(self._on_section_primary_clicked)
        section_actions.addWidget(self.section_primary_button)
        self.section_secondary_button = QPushButton("Secondary Action")
        self.section_secondary_button.setObjectName("SectionAction")
        self.section_secondary_button.clicked.connect(self._on_section_secondary_clicked)
        section_actions.addWidget(self.section_secondary_button)
        section_actions.addStretch(1)
        section_layout.addLayout(section_actions)

        self.section_meta_label = QLabel("")
        self.section_meta_label.setObjectName("SectionMeta")
        self.section_meta_label.setWordWrap(True)
        section_layout.addWidget(self.section_meta_label)

        layout.addWidget(self.home_panel)
        layout.addWidget(self.section_panel)

        self.status_card = QFrame()
        self.status_card.setObjectName("StatusCard")
        status_layout = QGridLayout(self.status_card)
        status_layout.setContentsMargins(12, 10, 12, 10)
        status_layout.setVerticalSpacing(8)
        status_layout.setHorizontalSpacing(10)
        status_layout.setColumnStretch(1, 1)

        self.output_path_value = self._add_status_row(status_layout, 0, "folder", "Output")
        self.ffmpeg_value = self._add_status_row(status_layout, 1, "ffmpeg", "FFmpeg")
        self.mic_value = self._add_status_row(status_layout, 2, "mic", "Microphone")
        self.capture_mode_value = self._add_status_row(status_layout, 3, "video", "Capture Mode")
        self.region_value = self._add_status_row(status_layout, 4, "capture_region", "Selected Region")
        self.source_value = self._add_status_row(status_layout, 5, "settings", "Source")
        self.system_audio_value = self._add_status_row(status_layout, 6, "audio", "System Audio")
        self.status_card.setVisible(False)

        layout.addWidget(self.status_card)
        layout.addStretch(1)
        parent_layout.addWidget(workspace, 1)

        for btn in (
            self.change_recordings_button,
            self.screenshot_button,
            self.record_button,
            self.stop_button,
            self.select_region_button,
            self.clear_region_button,
            self.select_source_button,
            self.clear_source_button,
            self.sync_test_button,
            self.section_primary_button,
            self.section_secondary_button,
        ):
            btn.setCursor(Qt.PointingHandCursor)

    def _configure_form_panel_layout(self, grid: QGridLayout) -> None:
        grid.setContentsMargins(18, 16, 18, 16)
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(12)
        grid.setColumnMinimumWidth(0, 156)
        grid.setColumnStretch(1, 1)
        grid.setColumnMinimumWidth(2, 72)

    def _create_toolbar_button(self, mode_key: str, tooltip: str, icon_name: str) -> QPushButton:
        btn = QPushButton()
        btn.setObjectName("ToolbarModeButton")
        btn.setIcon(build_icon(icon_name, 18))
        btn.setIconSize(QSize(18, 18))
        btn.setFixedSize(40, 40)
        btn.setCheckable(True)
        btn.setToolTip(tooltip)
        btn.clicked.connect(lambda _checked=False, m=mode_key: self._set_capture_mode(m))
        return btn

    def _create_nav_button(
        self,
        section_key: str,
        text: str,
        icon_name: str,
        active: bool = False,
    ) -> QPushButton:
        btn = QPushButton(text)
        btn.setObjectName("NavButton")
        btn.setIcon(build_icon(icon_name, 14))
        btn.setIconSize(QSize(14, 14))
        btn.setProperty("active", "true" if active else "false")
        btn.setCursor(Qt.PointingHandCursor)
        btn.clicked.connect(lambda _checked=False, s=section_key: self._set_sidebar_section(s))
        return btn

    def _create_home_tab_button(self, tab_key: str, text: str, active: bool = False) -> QPushButton:
        btn = QPushButton(text)
        btn.setObjectName("HomeTabButton")
        btn.setProperty("active", "true" if active else "false")
        btn.setCursor(Qt.PointingHandCursor)
        btn.clicked.connect(lambda _checked=False, t=tab_key: self._set_home_tab(t))
        return btn

    def _create_library_page(self, tab_key: str, title: str) -> QWidget:
        panel = QFrame()
        panel.setObjectName("LibraryPanel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        title_label = QLabel(f"{title} Library")
        title_label.setObjectName("LibraryTitle")
        layout.addWidget(title_label)

        meta_label = QLabel("")
        meta_label.setObjectName("LibraryMeta")
        layout.addWidget(meta_label)

        search_row = QHBoxLayout()
        search_row.setSpacing(8)
        search_label = QLabel("Search")
        search_label.setObjectName("LibraryMeta")
        search_input = QLineEdit()
        search_input.setPlaceholderText("Filter by filename...")
        search_input.textChanged.connect(lambda _text, t=tab_key: self._refresh_library_tab(t))
        search_row.addWidget(search_label)
        search_row.addWidget(search_input, 1)
        layout.addLayout(search_row)

        table = QTableWidget(0, 4)
        table.setObjectName("LibraryTable")
        table.setHorizontalHeaderLabels(["Filename", "Duration", "Size", "Created"])
        table.verticalHeader().setVisible(False)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setAlternatingRowColors(True)
        table.setSortingEnabled(False)
        table.horizontalHeader().setStretchLastSection(False)
        table.setColumnWidth(0, 380)
        table.setColumnWidth(1, 92)
        table.setColumnWidth(2, 100)
        table.setColumnWidth(3, 150)
        table.itemSelectionChanged.connect(lambda t=tab_key: self._update_library_action_state(t))
        layout.addWidget(table, 1)

        actions = QHBoxLayout()
        actions.setSpacing(8)

        refresh_button = QPushButton("Refresh")
        refresh_button.setObjectName("InlineButton")
        refresh_button.setIcon(build_icon("settings", 14))
        refresh_button.setCursor(Qt.PointingHandCursor)
        refresh_button.clicked.connect(lambda _checked=False, t=tab_key: self._refresh_library_tab(t))
        actions.addWidget(refresh_button)

        open_button = QPushButton("Open")
        open_button.setObjectName("InlineButton")
        open_button.setIcon(build_icon("recordings", 14))
        open_button.setCursor(Qt.PointingHandCursor)
        open_button.setEnabled(False)
        open_button.clicked.connect(lambda _checked=False, t=tab_key: self._open_selected_library_file(t))
        actions.addWidget(open_button)

        rename_button = QPushButton("Rename")
        rename_button.setObjectName("InlineButton")
        rename_button.setIcon(build_icon("settings", 14))
        rename_button.setCursor(Qt.PointingHandCursor)
        rename_button.setEnabled(False)
        rename_button.clicked.connect(lambda _checked=False, t=tab_key: self._rename_selected_library_file(t))
        actions.addWidget(rename_button)

        delete_button = QPushButton("Delete")
        delete_button.setObjectName("InlineButton")
        delete_button.setIcon(build_icon("clear", 14))
        delete_button.setCursor(Qt.PointingHandCursor)
        delete_button.setEnabled(False)
        delete_button.clicked.connect(lambda _checked=False, t=tab_key: self._delete_selected_library_file(t))
        actions.addWidget(delete_button)

        reveal_button = QPushButton("Reveal")
        reveal_button.setObjectName("InlineButton")
        reveal_button.setIcon(build_icon("folder", 14))
        reveal_button.setCursor(Qt.PointingHandCursor)
        reveal_button.setEnabled(False)
        reveal_button.clicked.connect(lambda _checked=False, t=tab_key: self._reveal_selected_library_file(t))
        actions.addWidget(reveal_button)

        open_folder_button = QPushButton("Open Folder")
        open_folder_button.setObjectName("InlineButton")
        open_folder_button.setIcon(build_icon("folder", 14))
        open_folder_button.setCursor(Qt.PointingHandCursor)
        open_folder_button.clicked.connect(self._open_recordings_folder)
        actions.addWidget(open_folder_button)

        actions.addStretch(1)
        layout.addLayout(actions)

        self.library_meta_labels[tab_key] = meta_label
        self.library_search_inputs[tab_key] = search_input
        self.library_tables[tab_key] = table
        self.library_rows[tab_key] = []
        self.library_open_buttons[tab_key] = open_button
        self.library_rename_buttons[tab_key] = rename_button
        self.library_delete_buttons[tab_key] = delete_button
        self.library_reveal_buttons[tab_key] = reveal_button
        return panel

    def _set_home_tab(self, tab_key: str, announce: bool = True) -> None:
        if tab_key not in self.home_tab_buttons:
            return

        self.current_home_tab = tab_key
        for key, button in self.home_tab_buttons.items():
            button.setProperty("active", "true" if key == tab_key else "false")
            self._repolish(button)

        index = self.home_tab_indices.get(tab_key)
        if index is not None:
            self.home_stack.setCurrentIndex(index)

        if tab_key == "get_started":
            self._set_capture_mode(self.current_mode, announce=False)
            if announce:
                self._set_status_chip("good", "Ready")
            return

        self._refresh_library_tab(tab_key)
        tab_names = {"videos": "Videos", "images": "Images", "audios": "Audios"}
        self.hint_label.setText(f"{tab_names[tab_key]} library")
        if announce:
            self._set_status_chip("good", "Library View")

    def _library_extensions(self, tab_key: str) -> tuple[str, ...]:
        if tab_key == "videos":
            return (".mp4", ".mkv", ".mov", ".avi", ".webm")
        if tab_key == "images":
            return (".png", ".jpg", ".jpeg", ".bmp", ".webp")
        if tab_key == "audios":
            return (".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".opus")
        return tuple()

    def _refresh_library_tab(self, tab_key: str) -> None:
        meta_label = self.library_meta_labels.get(tab_key)
        search_input = self.library_search_inputs.get(tab_key)
        table = self.library_tables.get(tab_key)
        if meta_label is None or search_input is None or table is None:
            return

        if self.recorder is None:
            ffmpeg_path = self.ff.path if self.ff.path else "ffmpeg"
            self.recorder = RecorderController(
                ffmpeg_path=ffmpeg_path,
                recordings_dir=self.paths.recordings_dir,
                temp_dir=self.paths.temp_dir,
            )

        exts = self._library_extensions(tab_key)
        query = search_input.text().strip()
        try:
            rows = self.recorder.list_recordings(extensions=exts, search_query=query)
        except Exception as e:
            self.library_rows[tab_key] = []
            table.setRowCount(0)
            self._update_library_action_state(tab_key)
            meta_label.setText("Failed to load library")
            QMessageBox.critical(self, "CAPTRIX", f"Failed to load library:\n{e}")
            return

        self.library_rows[tab_key] = rows
        table.setRowCount(len(rows))
        for row_index, item in enumerate(rows):
            table.setItem(row_index, 0, QTableWidgetItem(item.filename))
            table.setItem(row_index, 1, QTableWidgetItem(self._format_duration(item.duration_sec)))
            table.setItem(row_index, 2, QTableWidgetItem(self._format_size(item.size_bytes)))
            table.setItem(row_index, 3, QTableWidgetItem(item.created_at.strftime("%Y-%m-%d %H:%M:%S")))

        summary = f"{len(rows)} file(s) in {self.paths.recordings_dir}"
        if query:
            summary += f"  |  Filter: \"{query}\""
        meta_label.setText(summary)
        self._update_library_action_state(tab_key)

    def _format_duration(self, duration_sec: float | None) -> str:
        if duration_sec is None:
            return "N/A"
        whole = max(0, int(round(duration_sec)))
        hours = whole // 3600
        minutes = (whole % 3600) // 60
        seconds = whole % 60
        if hours > 0:
            return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
        return f"{minutes:02d}:{seconds:02d}"

    def _format_size(self, size_bytes: int) -> str:
        value = float(max(0, size_bytes))
        units = ["B", "KB", "MB", "GB", "TB"]
        for unit in units:
            if value < 1024.0 or unit == units[-1]:
                if unit == "B":
                    return f"{int(value)} {unit}"
                return f"{value:.1f} {unit}"
            value /= 1024.0
        return "0 B"

    def _selected_library_item(self, tab_key: str) -> RecordingLibraryItem | None:
        table = self.library_tables.get(tab_key)
        rows = self.library_rows.get(tab_key)
        if table is None or rows is None:
            return None
        selected_rows = table.selectionModel().selectedRows() if table.selectionModel() else []
        if not selected_rows:
            return None
        row_index = selected_rows[0].row()
        if row_index < 0 or row_index >= len(rows):
            return None
        return rows[row_index]

    def _update_library_action_state(self, tab_key: str) -> None:
        selected = self._selected_library_item(tab_key)
        has_selection = selected is not None
        open_button = self.library_open_buttons.get(tab_key)
        rename_button = self.library_rename_buttons.get(tab_key)
        delete_button = self.library_delete_buttons.get(tab_key)
        reveal_button = self.library_reveal_buttons.get(tab_key)
        for button in (open_button, rename_button, delete_button, reveal_button):
            if button is not None:
                button.setEnabled(has_selection)

    def _open_selected_library_file(self, tab_key: str) -> None:
        selected = self._selected_library_item(tab_key)
        if selected is None:
            QMessageBox.warning(self, "CAPTRIX", "Select a file first.")
            return
        try:
            self._open_target(selected.path)
            self._set_status_chip("good", "Opened File")
        except Exception as e:
            QMessageBox.critical(self, "CAPTRIX", f"Failed to open file:\n{e}")

    def _rename_selected_library_file(self, tab_key: str) -> None:
        selected = self._selected_library_item(tab_key)
        if selected is None:
            QMessageBox.warning(self, "CAPTRIX", "Select a file first.")
            return
        if self.recorder is None:
            return

        proposed, ok = QInputDialog.getText(
            self,
            "Rename Recording",
            "New filename:",
            text=selected.path.stem,
        )
        if not ok:
            return

        try:
            new_path = self.recorder.rename_recording(selected.path, proposed.strip())
            self._refresh_library_tab(tab_key)
            self._set_status_chip("good", "Renamed")
            QMessageBox.information(self, "CAPTRIX", f"Renamed to:\n{new_path.name}")
        except Exception as e:
            QMessageBox.critical(self, "CAPTRIX", f"Failed to rename file:\n{e}")

    def _delete_selected_library_file(self, tab_key: str) -> None:
        selected = self._selected_library_item(tab_key)
        if selected is None:
            QMessageBox.warning(self, "CAPTRIX", "Select a file first.")
            return
        if self.recorder is None:
            return

        answer = QMessageBox.question(
            self,
            "Delete Recording",
            f"Delete this file?\n{selected.path.name}",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        try:
            self.recorder.delete_recording(selected.path)
            self._refresh_library_tab(tab_key)
            self._set_status_chip("good", "Deleted")
        except Exception as e:
            QMessageBox.critical(self, "CAPTRIX", f"Failed to delete file:\n{e}")

    def _reveal_selected_library_file(self, tab_key: str) -> None:
        selected = self._selected_library_item(tab_key)
        if selected is None:
            QMessageBox.warning(self, "CAPTRIX", "Select a file first.")
            return
        try:
            self._reveal_in_file_manager(selected.path)
            self._set_status_chip("good", "Revealed")
        except Exception as e:
            QMessageBox.critical(self, "CAPTRIX", f"Failed to reveal file:\n{e}")

    def _create_mode_tile(self, mode_key: str, title: str, subtitle: str, icon_name: str) -> QPushButton:
        tile = QPushButton(f"{title}\n{subtitle}")
        tile.setObjectName("ModeTile")
        tile.setIcon(build_icon(icon_name, 26))
        tile.setIconSize(QSize(26, 26))
        tile.setMinimumHeight(132)
        tile.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        tile.setCheckable(True)
        tile.setProperty("active", "false")
        tile.clicked.connect(lambda _checked=False, m=mode_key: self._set_capture_mode(m))
        return tile

    def _add_status_row(self, grid: QGridLayout, row: int, icon_name: str, name: str) -> QLabel:
        icon = QLabel()
        icon.setPixmap(build_icon(icon_name, 14).pixmap(14, 14))
        icon.setFixedSize(16, 16)

        key = QLabel(name)
        key.setObjectName("StatusKey")

        value = QLabel("-")
        value.setObjectName("StatusValue")
        value.setWordWrap(True)
        value.setTextInteractionFlags(Qt.TextSelectableByMouse)

        grid.addWidget(icon, row, 0, Qt.AlignTop)
        grid.addWidget(key, row, 1, Qt.AlignTop)
        grid.addWidget(value, row, 2)
        return value

    def _apply_theme(self) -> None:
        self.setStyleSheet(
            """
            QWidget#Root {
                background: #f2f5f9;
                color: #1f2a37;
                font-family: "Bahnschrift", "Segoe UI";
                font-size: 10pt;
            }
            QFrame#TopBar {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #ffffff, stop:1 #f7fbff);
                border-bottom: 1px solid #d7e1ed;
            }
            QLabel#BrandTitle {
                color: #0f2a43;
                font-size: 16pt;
                font-weight: 700;
                letter-spacing: 0.8px;
            }

            QPushButton#ToolbarModeButton {
                background: #eef4fb;
                border: 1px solid #bfd2e8;
                border-radius: 10px;
                padding: 4px;
            }
            QPushButton#ToolbarModeButton:hover {
                background: #e1ecf9;
                border-color: #8fb4dd;
            }
            QPushButton#ToolbarModeButton:checked, QPushButton#ToolbarModeButton[active="true"] {
                background: #d8e8fb;
                border: 1px solid #5f95d0;
            }

            QLabel#StatusChip {
                border-radius: 12px;
                padding: 7px 13px;
                font-weight: 700;
                min-height: 28px;
                background-color: #e8f0fb;
                border: 1px solid #c4d7ee;
                color: #20405f;
            }
            QLabel#StatusChip[kind="good"] { color: #0f5a3f; background-color: #d9f5e9; border: 1px solid #78c9a6; }
            QLabel#StatusChip[kind="warn"] { color: #7a4f0d; background-color: #fff1d9; border: 1px solid #e7be73; }
            QLabel#StatusChip[kind="error"] { color: #8a2137; background-color: #ffe0e7; border: 1px solid #f19caf; }
            QLabel#StatusChip[kind="live"] { color: #8a152d; background-color: #ffd8e1; border: 1px solid #ed8ba1; }
            QLabel#StatusChip[kind="busy"] { color: #1d4970; background-color: #dfeeff; border: 1px solid #94bee8; }

            QPushButton#TopSecondaryButton, QPushButton#InlineButton {
                background: #f7fbff;
                border: 1px solid #bbcee5;
                border-radius: 10px;
                padding: 8px 14px;
                min-height: 32px;
                color: #18344f;
                font-weight: 600;
            }
            QPushButton#TopSecondaryButton:hover, QPushButton#InlineButton:hover {
                background: #ecf4ff;
                border-color: #8fb3dc;
            }
            QPushButton#InlineButton { min-width: 130px; }

            QPushButton#TopRecordButton {
                background: #1f9f6b;
                border: 1px solid #46c995;
                border-radius: 10px;
                padding: 8px 16px;
                min-height: 32px;
                color: #f4fff9;
                font-weight: 700;
            }
            QPushButton#TopRecordButton:hover { background: #22af75; }
            QPushButton#TopShotButton {
                background: #ecf3ff;
                border: 1px solid #98bae1;
                border-radius: 10px;
                padding: 8px 16px;
                min-height: 32px;
                color: #174168;
                font-weight: 700;
            }
            QPushButton#TopShotButton:hover { background: #dfeeff; }
            QPushButton#TopStopButton {
                background: #d95563;
                border: 1px solid #f19daa;
                border-radius: 10px;
                padding: 8px 16px;
                min-height: 32px;
                color: #fff5f7;
                font-weight: 700;
            }
            QPushButton#TopStopButton:hover { background: #e16471; }
            QPushButton:disabled {
                color: #90a2b6;
                background-color: #e7edf4;
                border-color: #ccd7e3;
            }

            QLabel#RecIndicator {
                border-radius: 17px;
                background-color: #ffffff;
                border: 1px solid #c4d4e6;
            }
            QLabel#RecIndicator[active="true"] {
                border: 2px solid #e75267;
                background-color: #ffe8ee;
            }

            QFrame#HintBar {
                background-color: #edf5ff;
                border-bottom: 1px solid #d7e5f4;
            }
            QLabel#HintLabel { color: #204362; font-size: 9.9pt; }
            QLabel#OutputHintLabel { color: #4a6787; font-size: 9.1pt; }

            QFrame#CenterFrame { background: transparent; }
            QFrame#Sidebar {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #17324a, stop:1 #1e3d5b);
                border: 1px solid #10283d;
                border-radius: 14px;
            }
            QPushButton#NavButton {
                background-color: transparent;
                border: 0;
                text-align: left;
                color: #d2e5f9;
                border-radius: 9px;
                padding: 10px 12px;
                font-size: 10.2pt;
            }
            QPushButton#NavButton:hover { background-color: #2b4b69; }
            QPushButton#NavButton[active="true"] {
                color: #17324a;
                font-weight: 700;
                background-color: #e9f3ff;
            }
            QLabel#SidebarFooter {
                border: 1px solid #5b7a9a;
                color: #d8e9fb;
                border-radius: 8px;
                padding: 7px;
                font-size: 9pt;
            }

            QFrame#Workspace {
                background-color: #ffffff;
                border: 1px solid #d3dfec;
                border-radius: 14px;
            }
            QPushButton#HomeTabButton {
                background-color: transparent;
                border: 0;
                color: #4f6a84;
                font-size: 10.3pt;
                padding: 3px 0;
                text-align: left;
            }
            QPushButton#HomeTabButton:hover { color: #1f3e5e; }
            QPushButton#HomeTabButton[active="true"] {
                color: #0f2a43;
                font-weight: 700;
                border-bottom: 3px solid #e69532;
            }
            QStackedWidget#HomeStack { background: transparent; border: 0; }
            QScrollArea#GetStartedScroll { background: transparent; border: 0; }
            QScrollArea#GetStartedScroll > QWidget > QWidget { background: transparent; }

            QScrollBar:vertical {
                background: #eef3f8;
                width: 11px;
                border-radius: 5px;
                margin: 0;
            }
            QScrollBar::handle:vertical {
                background: #b8cade;
                min-height: 28px;
                border-radius: 5px;
            }
            QScrollBar::handle:vertical:hover { background: #97b2d0; }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }

            QPushButton#ModeTile {
                background-color: #f7fbff;
                border: 1px solid #cad8e8;
                border-radius: 12px;
                color: #16354f;
                text-align: center;
                padding: 14px;
                font-size: 10.4pt;
                font-weight: 600;
                line-height: 1.35;
            }
            QPushButton#ModeTile:hover {
                background-color: #ecf4ff;
                border-color: #87aed8;
            }
            QPushButton#ModeTile[active="true"] {
                background-color: #e5f0ff;
                border: 1px solid #3f81c4;
            }
            QLabel#ModeDescription {
                color: #2a4a67;
                font-size: 10.9pt;
                padding: 2px 2px 5px 2px;
            }

            QFrame#VideoEncodePanel, QFrame#WebcamPanel, QFrame#AudioMixPanel, QFrame#LibraryPanel, QFrame#SectionPanel, QFrame#StatusCard {
                background-color: #fbfdff;
                border: 1px solid #d3e0ee;
                border-radius: 12px;
            }
            QLabel#VideoLabel, QLabel#WebcamLabel, QLabel#AudioLabel {
                color: #3d5f81;
                font-weight: 600;
            }
            QLabel#VideoHint, QLabel#WebcamHint, QLabel#AudioHint {
                color: #6484a5;
                font-size: 9.3pt;
            }

            QComboBox#VideoCombo, QComboBox#WebcamCombo, QComboBox#AudioCombo {
                background-color: #ffffff;
                border: 1px solid #b8cbe2;
                border-radius: 8px;
                padding: 5px 10px;
                color: #1e3043;
                min-height: 32px;
            }

            QCheckBox#WebcamToggle, QCheckBox#AudioToggle {
                color: #173a59;
                font-weight: 700;
                spacing: 7px;
            }
            QLabel#WebcamValue, QLabel#AudioValue {
                color: #2a4561;
                font-weight: 700;
                min-width: 52px;
            }

            QCheckBox::indicator {
                width: 17px;
                height: 17px;
                border-radius: 4px;
                border: 1px solid #88a9c9;
                background-color: #ffffff;
            }
            QCheckBox::indicator:checked {
                background-color: #2f80d0;
                border-color: #1d67ad;
            }

            QSlider::groove:horizontal {
                height: 7px;
                border-radius: 3px;
                background: #d5e2f0;
            }
            QSlider::handle:horizontal {
                width: 16px;
                margin: -6px 0;
                border-radius: 8px;
                background: #2f80d0;
                border: 1px solid #1f67ab;
            }
            QSlider::handle:horizontal:hover { background: #3d92e4; }

            QLineEdit {
                background-color: #ffffff;
                border: 1px solid #b8cbe2;
                border-radius: 8px;
                padding: 6px 10px;
                min-height: 30px;
                color: #1f2a37;
            }
            QComboBox::drop-down { border: 0; width: 24px; }

            QFrame#LibraryPanel { padding: 12px; }
            QLabel#LibraryTitle { color: #12324d; font-size: 11.4pt; font-weight: 700; }
            QLabel#LibraryMeta { color: #597a9b; font-size: 9.3pt; }
            QLabel#LibraryList { color: #2b4663; font-size: 9.8pt; }
            QTableWidget#LibraryTable {
                background-color: #ffffff;
                alternate-background-color: #f5f9fd;
                border: 1px solid #bed0e4;
                gridline-color: #d3e1ef;
                color: #1f2a37;
                border-radius: 8px;
            }
            QTableWidget#LibraryTable::item:selected {
                background-color: #d9eaff;
                color: #14314a;
            }
            QHeaderView::section {
                background-color: #ecf4fc;
                color: #1f415f;
                border: 1px solid #c5d8ea;
                padding: 6px 8px;
                font-weight: 600;
            }

            QLabel#SectionTitle { color: #0f2a43; font-size: 12.2pt; font-weight: 700; }
            QLabel#SectionBody { color: #2a4b67; font-size: 10.1pt; }
            QLabel#SectionMeta { color: #6484a5; font-size: 9.4pt; }
            QPushButton#SectionAction {
                background: #f7fbff;
                border: 1px solid #bbcee5;
                border-radius: 10px;
                padding: 8px 14px;
                min-height: 32px;
                color: #17344f;
                font-weight: 600;
            }
            QPushButton#SectionAction:hover {
                background: #ecf4ff;
                border-color: #8fb3dc;
            }

            QLabel#StatusKey { color: #4a6d8d; font-weight: 600; }
            QLabel#StatusValue { color: #1f3a55; }
            """
        )

    def _repolish(self, widget: QWidget) -> None:
        widget.style().unpolish(widget)
        widget.style().polish(widget)
        widget.update()

    def _set_status_chip(self, kind: str, text: str) -> None:
        self.status_chip.setProperty("kind", kind)
        self.status_chip.setText(text)
        self._repolish(self.status_chip)

    def _set_rec_indicator(self, active: bool) -> None:
        self.rec_indicator.setProperty("active", "true" if active else "false")
        self._repolish(self.rec_indicator)

    def _on_section_primary_clicked(self) -> None:
        if self._section_primary_handler is not None:
            self._section_primary_handler()

    def _on_section_secondary_clicked(self) -> None:
        if self._section_secondary_handler is not None:
            self._section_secondary_handler()

    def _set_section_actions(
        self,
        primary_text: str,
        primary_handler: Callable[[], None] | None,
        secondary_text: str | None = None,
        secondary_handler: Callable[[], None] | None = None,
    ) -> None:
        self._section_primary_handler = primary_handler
        self._section_secondary_handler = secondary_handler

        self.section_primary_button.setText(primary_text)
        self.section_primary_button.setEnabled(primary_handler is not None)

        if secondary_text:
            self.section_secondary_button.setText(secondary_text)
            self.section_secondary_button.setVisible(True)
            self.section_secondary_button.setEnabled(secondary_handler is not None)
        else:
            self.section_secondary_button.setVisible(False)
            self.section_secondary_button.setEnabled(False)

    def _section_meta_text(self, section_key: str) -> str:
        if section_key == "general":
            return f"Recordings: {self.paths.recordings_dir}\nTemp cache: {self.paths.temp_dir}"
        if section_key == "video":
            return (
                f"Active mode: {self._capture_mode_summary()}\n"
                f"Current source: {self._source_summary()}\n"
                f"Video Encode: {self._video_encoding_summary()}\n"
                f"Webcam: {self._webcam_summary()}\n"
                f"Audio Mix: {self._system_audio_summary()}"
            )
        if section_key == "image":
            return f"Region mode: {self._capture_mode_summary()}\nSelected region: {self._region_summary()}"
        ffmpeg_info = self.ff.version or self.ff.path or "Unavailable"
        checked = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        effective_encoder, note = self._effective_encoder_preview()
        lines = [
            f"Runtime: {self._runtime_platform_summary()}",
            f"FFmpeg: {ffmpeg_info}",
            "Capture stack: gdigrab + dshow + wasapi",
            f"Encoding: Auto -> {effective_encoder} | {self._quality_preset_label()}",
            f"Detected GPU encoders: {self._gpu_encoder_support_summary()}",
            f"Current mode: {self._capture_mode_summary()}",
            f"Storage: {self.paths.recordings_dir}",
            f"Checked: {checked}",
        ]
        if note:
            lines.append(f"Encoder note: {note}")
        return "\n".join(lines)

    def _runtime_platform_summary(self) -> str:
        py_version = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
        system_name = platform.system() or "Unknown"
        system_release = platform.release() or "Unknown"
        return f"Python {py_version} on {system_name} {system_release}"

    def _about_overview_text(self) -> str:
        return (
            "CAPTRIX is a Windows desktop recording workstation for tutorials, demos, and issue reporting.\n"
            "It combines a Qt control surface with an FFmpeg pipeline to provide stable capture, automatic hardware-aware encoding,\n"
            "webcam picture-in-picture overlays, and mixed microphone plus desktop audio recording."
        )

    def _about_runtime_lines(self) -> list[str]:
        ffmpeg_info = self.ff.version or self.ff.path or "Unavailable"
        checked = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        effective_encoder, note = self._effective_encoder_preview()
        lines = [
            "CAPTRIX - Desktop Capture Workstation",
            "",
            "Overview:",
            "CAPTRIX records tutorials, product demos, and bug reproduction clips with a production-ready FFmpeg backend.",
            "It supports fullscreen/region/window/game/device capture, optional webcam overlay, and resilient MKV to MP4 finalization.",
            "",
            "Capabilities:",
            "- Capture modes: Region, Fullscreen, Window, Game, Device, Audio-only",
            "- Encoder strategy: Auto-select NVIDIA/Intel/AMD GPU when available, fallback to CPU x264",
            "- Audio path: Microphone plus optional desktop loopback (WASAPI)",
            "- Recovery: Unfinished sessions can be recovered on startup",
            "",
            "Current runtime:",
            f"- Platform: {self._runtime_platform_summary()}",
            f"- FFmpeg: {ffmpeg_info}",
            f"- Capture mode: {self._capture_mode_summary()}",
            f"- Source: {self._source_summary()}",
            f"- Video encoding: Auto -> {effective_encoder} ({self._quality_preset_label()})",
            f"- Detected GPU encoders: {self._gpu_encoder_support_summary()}",
            f"- Webcam: {self._webcam_summary()}",
            f"- Audio mix: {self._system_audio_summary()}",
            f"- Microphone: {self.mic_name or 'Not detected'} | Mic volume {self.mic_volume_percent}%",
            f"- Output folder: {self.paths.recordings_dir}",
            f"- Temp cache: {self.paths.temp_dir}",
            f"- Checked: {checked}",
        ]
        if note:
            lines.append(f"- Encoder note: {note}")
        lines.extend(["", "License: MIT"])
        return lines

    def _about_runtime_details(self) -> str:
        return "\n".join(self._about_runtime_lines())

    def _copy_about_details(self) -> None:
        QApplication.clipboard().setText(self._about_runtime_details())
        self._set_status_chip("good", "Runtime Report Copied")

    def _show_about_dialog(self) -> None:
        msg = QMessageBox(self)
        msg.setWindowTitle("About CAPTRIX")
        msg.setIcon(QMessageBox.Icon.Information)
        msg.setText("CAPTRIX Desktop Capture Workstation")
        msg.setInformativeText(
            "Use the runtime report for diagnostics, setup validation, and support troubleshooting."
        )
        msg.setDetailedText(self._about_runtime_details())
        msg.exec()

    def _open_target(self, target: Path) -> None:
        if not target.exists():
            raise RuntimeError(f"Path does not exist: {target}")

        target_str = str(target)
        if sys.platform.startswith("win"):
            if target.is_file():
                os.startfile(target_str)  # type: ignore[attr-defined]
            else:
                subprocess.Popen(["explorer", target_str])
        elif sys.platform == "darwin":
            subprocess.Popen(["open", target_str])
        else:
            subprocess.Popen(["xdg-open", target_str])

    def _reveal_in_file_manager(self, target: Path) -> None:
        if not target.exists():
            raise RuntimeError(f"Path does not exist: {target}")
        target_str = str(target)
        if sys.platform.startswith("win"):
            subprocess.Popen(["explorer", "/select,", target_str])
        elif sys.platform == "darwin":
            subprocess.Popen(["open", "-R", target_str])
        else:
            self._open_target(target.parent)

    def _open_recordings_folder(self) -> None:
        try:
            self._open_target(self.paths.recordings_dir)
            self._set_status_chip("good", "Opened Recordings Folder")
        except Exception as e:
            QMessageBox.critical(self, "CAPTRIX", f"Failed to open recordings folder:\n{e}")

    def _check_recovery_sessions_on_startup(self) -> None:
        if self.recorder is None:
            ffmpeg_path = self.ff.path if self.ff.path else "ffmpeg"
            self.recorder = RecorderController(
                ffmpeg_path=ffmpeg_path,
                recordings_dir=self.paths.recordings_dir,
                temp_dir=self.paths.temp_dir,
            )
        try:
            sessions = self.recorder.list_unfinished_sessions()
        except Exception:
            return
        if not sessions:
            return

        total_size = sum(max(0, s.size_bytes) for s in sessions)
        details = self._recovery_sessions_details(sessions)
        msg = QMessageBox(self)
        msg.setWindowTitle("CAPTRIX Recovery")
        msg.setIcon(QMessageBox.Icon.Warning)
        msg.setText(f"Found {len(sessions)} unfinished session(s).")
        msg.setInformativeText(
            f"Temp data size: {self._format_size(total_size)}\n"
            "Recover will remux MKV to MP4 safely. Delete will remove temp sessions."
        )
        msg.setDetailedText(details)
        recover_button = msg.addButton("Recover All", QMessageBox.ButtonRole.AcceptRole)
        delete_button = msg.addButton("Delete All", QMessageBox.ButtonRole.DestructiveRole)
        msg.addButton("Later", QMessageBox.ButtonRole.RejectRole)
        msg.exec()

        clicked = msg.clickedButton()
        if clicked is recover_button:
            self._recover_sessions(sessions)
        elif clicked is delete_button:
            self._delete_recovery_sessions(sessions)

    def _recovery_sessions_details(self, sessions: list[RecoverySession]) -> str:
        lines: list[str] = []
        for index, session in enumerate(sessions, start=1):
            when = session.start_time or "unknown"
            lines.append(
                f"{index}. {session.session_id}\n"
                f"   Status: {session.status}\n"
                f"   Started: {when}\n"
                f"   Size: {self._format_size(session.size_bytes)}\n"
                f"   Temp: {session.mkv_path}"
            )
        return "\n\n".join(lines)

    def _recover_sessions(self, sessions: list[RecoverySession]) -> None:
        if self.recorder is None:
            return
        recovered: list[Path] = []
        failed: list[str] = []
        for session in sessions:
            try:
                output = self.recorder.recover_session(session)
                recovered.append(output)
            except Exception as e:
                failed.append(f"{session.session_id}: {e}")

        self.refresh_status()
        if recovered and not failed:
            self._set_status_chip("good", "Recovered")
            QMessageBox.information(
                self,
                "CAPTRIX Recovery",
                f"Recovered {len(recovered)} session(s).",
            )
            return

        if recovered:
            self._set_status_chip("warn", "Recovered With Issues")
            QMessageBox.warning(
                self,
                "CAPTRIX Recovery",
                f"Recovered {len(recovered)} session(s), failed {len(failed)}.\n\n"
                + "\n".join(failed[:6]),
            )
            return

        self._set_status_chip("error", "Recovery Failed")
        QMessageBox.critical(
            self,
            "CAPTRIX Recovery",
            "No sessions could be recovered.\n\n" + "\n".join(failed[:6]),
        )

    def _delete_recovery_sessions(self, sessions: list[RecoverySession]) -> None:
        if self.recorder is None:
            return
        answer = QMessageBox.question(
            self,
            "Delete Unfinished Sessions",
            "Delete all unfinished temp sessions? This cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        for session in sessions:
            try:
                self.recorder.delete_session(session)
            except Exception:
                pass
        self.refresh_status()
        self._set_status_chip("good", "Temp Cleaned")

    def _set_sidebar_section(self, section_key: str) -> None:
        if section_key not in self.nav_buttons:
            return

        self.current_section = section_key
        for key, button in self.nav_buttons.items():
            button.setProperty("active", "true" if key == section_key else "false")
            self._repolish(button)

        is_home = section_key in {"home", "video"}
        self.home_panel.setVisible(is_home)
        self.section_panel.setVisible(not is_home)

        if section_key == "home":
            self._set_home_tab(self.current_home_tab, announce=False)
            return

        if section_key == "video":
            self._set_home_tab("get_started", announce=False)
            self.hint_label.setText("Video encoder settings, webcam overlay, and audio mix")
            return

        if section_key == "general":
            self.section_title_label.setText("General Settings")
            self.section_body_label.setText("Manage storage location and recording session defaults.")
            self._set_section_actions(
                primary_text="Change Output Folder",
                primary_handler=self.on_change_recordings_clicked,
                secondary_text="Open Recordings Folder",
                secondary_handler=self._open_recordings_folder,
            )
        elif section_key == "video":
            self.section_title_label.setText("Video Settings")
            self.section_body_label.setText(
                "Encoder is auto-detected for best compatibility. Configure quality preset, webcam overlay, and mic/system audio mix."
            )
            self._set_section_actions(
                primary_text="Enable Webcam Overlay",
                primary_handler=lambda: self.webcam_enable_checkbox.setChecked(True),
                secondary_text="Disable Webcam Overlay",
                secondary_handler=lambda: self.webcam_enable_checkbox.setChecked(False),
            )
        elif section_key == "image":
            self.section_title_label.setText("Image Tools")
            self.section_body_label.setText("Capture still screenshots from fullscreen, region, window, game, or device source.")
            self._set_section_actions(
                primary_text="Take Screenshot",
                primary_handler=self.on_take_screenshot_clicked,
                secondary_text="Select Region",
                secondary_handler=self.on_select_region_clicked,
            )
        else:
            self.section_title_label.setText("About CAPTRIX")
            self.section_body_label.setText(self._about_overview_text())
            self._set_section_actions(
                primary_text="View Runtime Report",
                primary_handler=self._show_about_dialog,
                secondary_text="Copy Runtime Report",
                secondary_handler=self._copy_about_details,
            )

        self.section_meta_label.setText(self._section_meta_text(section_key))
        self.hint_label.setText(f"{self.section_title_label.text()} panel")

    def _capture_mode_summary(self) -> str:
        names = {
            "region": "Rectangle area",
            "fullscreen": "Fullscreen",
            "window": "Specific window",
            "device": "Device recording",
            "game": "Game recording",
            "audio": "Audio only",
        }
        return names.get(self.current_mode, self.current_mode)

    def _region_summary(self) -> str:
        if self.selected_region is None:
            return "No region selected"
        r = self.selected_region
        return f"{r.width}x{r.height} @ ({r.x}, {r.y})"

    def _source_summary(self) -> str:
        if self.current_mode == "window":
            return self.selected_window_title or "No window selected"
        if self.current_mode == "game":
            return self.selected_game_window_title or "No game window selected"
        if self.current_mode == "device":
            video = self.selected_device_video or "None"
            audio = self.selected_device_audio or "None"
            return f"Video: {video} | Audio: {audio}"
        if self.current_mode == "audio":
            return self.selected_audio_source or self.mic_name or "No audio source selected"
        return "N/A"

    def _capture_screen_rect(self) -> QRect:
        screen = None
        try:
            if self.windowHandle() is not None:
                screen = self.windowHandle().screen()
        except Exception:
            screen = None
        if screen is None:
            screen = self.screen()
        if screen is None:
            screen = QGuiApplication.primaryScreen()
        if screen is None:
            return QRect(0, 0, 1280, 720)
        return screen.geometry()

    def _sync_live_webcam_preview(self) -> None:
        recording = self.recorder is not None and self.recorder.is_recording()
        supports_overlay = self._mode_supports_webcam_overlay()
        has_device = bool(self.selected_webcam_device)

        if recording and self.webcam_enabled and supports_overlay and has_device:
            # Hide local preview while recording so it does not get captured on screen.
            self.webcam_preview_overlay.stop_preview()
            return

        should_show = (
            self.webcam_enabled
            and supports_overlay
            and has_device
            and not recording
        )
        if not should_show:
            self.webcam_preview_overlay.stop_preview()
            self._webcam_preview_error_shown = False
            return

        assert self.selected_webcam_device is not None
        started = self.webcam_preview_overlay.start_preview(self.selected_webcam_device)
        if not started:
            self.webcam_preview_overlay.stop_preview()
            if not self._webcam_preview_error_shown:
                self._webcam_preview_error_shown = True
                self.webcam_hint_label.setText(
                    "Failed to open live webcam preview. Recording overlay may still work."
                )
            return

        self._webcam_preview_error_shown = False
        self.webcam_preview_overlay.update_geometry_for_overlay(
            screen_rect=self._capture_screen_rect(),
            size_percent=self.webcam_size_percent,
            position=self.webcam_position,
            margin=24,
        )
        self.webcam_preview_overlay.show()

    def _mode_supports_webcam_overlay(self) -> bool:
        return self.current_mode in {"region", "fullscreen", "window", "game"}

    def _sync_webcam_devices(self, video_devices: list[str]) -> None:
        preferred = self.selected_webcam_device
        default_webcam = pick_default_webcam(video_devices)
        self.webcam_device_combo.blockSignals(True)
        self.webcam_device_combo.clear()

        if not video_devices:
            self.selected_webcam_device = None
            self.webcam_device_combo.addItem("No webcam detected")
            self.webcam_device_combo.setEnabled(False)
            self.webcam_enable_checkbox.blockSignals(True)
            self.webcam_enable_checkbox.setChecked(False)
            self.webcam_enable_checkbox.blockSignals(False)
            self.webcam_enabled = False
            self.webcam_enable_checkbox.setEnabled(False)
            self.webcam_device_combo.blockSignals(False)
            self._update_webcam_controls(recording=self.recorder is not None and self.recorder.is_recording())
            return

        self.webcam_device_combo.addItems(video_devices)
        selected = preferred if preferred in video_devices else default_webcam
        if selected is None:
            selected = video_devices[0]
        self.selected_webcam_device = selected
        self.webcam_device_combo.setCurrentText(selected)
        self.webcam_device_combo.blockSignals(False)
        self.webcam_enable_checkbox.setEnabled(True)
        self._update_webcam_controls(recording=self.recorder is not None and self.recorder.is_recording())

    def _webcam_summary(self) -> str:
        if not self.webcam_enabled:
            return "Webcam overlay disabled"
        if not self.selected_webcam_device:
            return "Webcam enabled - no device selected"

        position_label = next(
            (label for label, value in self.WEBCAM_POSITIONS.items() if value == self.webcam_position),
            "Bottom-Right",
        )
        return f"{self.selected_webcam_device} | {self.webcam_size_percent}% | {position_label}"

    def _mode_supports_video_encoding(self) -> bool:
        return self.current_mode != "audio"

    def _encoder_preference_label(self) -> str:
        return next(
            (label for label, value in self.ENCODER_OPTIONS.items() if value == self.video_encoder_preference),
            "Auto (Best Available)",
        )

    def _quality_preset_label(self) -> str:
        return next(
            (label for label, value in self.QUALITY_OPTIONS.items() if value == self.video_quality_preset),
            "Balanced",
        )

    def _gpu_encoder_support_summary(self) -> str:
        support = self.h264_encoder_support
        if support is None:
            return "Unknown"

        available: list[str] = []
        if support.nvidia:
            available.append("NVIDIA")
        if support.intel:
            available.append("Intel")
        if support.amd:
            available.append("AMD")
        return ", ".join(available) if available else "None"

    def _is_gpu_encoder_supported(self, encoder_key: str) -> bool:
        support = self.h264_encoder_support
        if support is None:
            return False
        if encoder_key == "nvidia":
            return support.nvidia
        if encoder_key == "intel":
            return support.intel
        if encoder_key == "amd":
            return support.amd
        return encoder_key == "cpu"

    def _effective_encoder_preview(self) -> tuple[str, str | None]:
        if not self.ff.found or self.recorder is None:
            return ("Unknown", "FFmpeg/recorder is not ready yet.")

        fps = 60 if self.current_mode == "game" else 30
        try:
            plan = self.recorder.resolve_video_encoding_plan(
                encoder_preference="auto",
                quality_preset=self.video_quality_preset,
                fps=fps,
            )
        except Exception as e:
            return ("CPU (x264)", f"Auto detection failed. Using CPU x264. Details: {e}")

        label = {
            "nvidia": "NVIDIA",
            "intel": "Intel",
            "amd": "AMD",
            "cpu": "CPU (x264)",
        }.get(plan.selected_encoder, plan.selected_encoder)
        return (label, plan.selection_note)

    def _video_encoding_summary(self) -> str:
        effective_encoder, note = self._effective_encoder_preview()
        summary = (
            f"Mode {self._encoder_preference_label()} | "
            f"Effective {effective_encoder} | "
            f"{self._quality_preset_label()} | "
            f"Detected GPU: {self._gpu_encoder_support_summary()}"
        )
        if note:
            summary = f"{summary} ({note})"
        return summary

    def _refresh_h264_encoder_support(self, refresh: bool = False) -> None:
        if not self.ff.found or self.recorder is None:
            self.h264_encoder_support = None
            return

        try:
            self.h264_encoder_support = self.recorder.get_h264_encoder_support(refresh=refresh)
        except Exception as e:
            self.h264_encoder_support = H264EncoderSupport(
                nvidia=False,
                intel=False,
                amd=False,
                error=str(e),
            )

    def _update_video_encoding_controls(self, recording: bool) -> None:
        supports_video = self._mode_supports_video_encoding()

        self.video_encoding_panel.setVisible(True)
        self.video_encoder_preference = "auto"
        self.encoder_combo.blockSignals(True)
        self.encoder_combo.setCurrentText(self._encoder_preference_label())
        self.encoder_combo.blockSignals(False)
        self.encoder_combo.setEnabled(False)
        self.quality_combo.setEnabled((not recording) and self.ff.found and supports_video)

        if not supports_video:
            self.video_encoding_hint_label.setText("Encoder settings apply to video capture modes only.")
            return
        if not self.ff.found:
            self.video_encoding_hint_label.setText("FFmpeg is unavailable. Encoder selection is disabled.")
            return

        effective_encoder, note = self._effective_encoder_preview()
        hint = (
            "Encoder mode: Auto-Detect | "
            f"Detected GPU encoders: {self._gpu_encoder_support_summary()} | "
            f"Effective encoder: {effective_encoder} | "
            f"Quality: {self._quality_preset_label()}"
        )
        if note:
            hint = f"{hint}. {note}"
        if self.h264_encoder_support is not None and self.h264_encoder_support.error:
            hint = f"{hint}. Probe warning: {self.h264_encoder_support.error}"
        self.video_encoding_hint_label.setText(hint)

    def _mode_supports_system_audio_mix(self) -> bool:
        return self.current_mode in {"region", "fullscreen", "window", "game"}

    def _system_audio_summary(self) -> str:
        if not self._mode_supports_system_audio_mix():
            return "Unavailable for current mode"
        if not self.system_audio_enabled:
            if not self.system_audio_devices:
                if self.system_audio_wasapi_supported:
                    return f"No loopback source | Mic {self.mic_volume_percent}%"
                return f"No WASAPI/loopback source | Mic {self.mic_volume_percent}%"
            return f"Off | Mic {self.mic_volume_percent}%"
        if self.selected_system_audio_device is None:
            return f"On (no device) | Mic {self.mic_volume_percent}%"
        return (
            f"{self.selected_system_audio_device.label} | "
            f"Mic {self.mic_volume_percent}% | System {self.system_audio_volume_percent}%"
        )

    def _sync_system_audio_devices(self, devices: list[SystemAudioDevice]) -> None:
        preferred = self.selected_system_audio_device
        default_device = pick_default_system_audio(devices)

        self.system_audio_devices = list(devices)
        self.system_audio_device_combo.blockSignals(True)
        self.system_audio_device_combo.clear()

        if not self.system_audio_devices:
            self.selected_system_audio_device = None
            self.system_audio_device_combo.addItem("No system audio source detected")
            self.system_audio_device_combo.setEnabled(False)
            self.system_audio_enable_checkbox.blockSignals(True)
            self.system_audio_enable_checkbox.setChecked(False)
            self.system_audio_enable_checkbox.blockSignals(False)
            self.system_audio_enabled = False
            self.system_audio_enable_checkbox.setEnabled(False)
            self.system_audio_device_combo.blockSignals(False)
            self._update_audio_mix_controls(recording=self.recorder is not None and self.recorder.is_recording())
            return

        for device in self.system_audio_devices:
            self.system_audio_device_combo.addItem(device.label, device)

        selected = preferred if preferred in self.system_audio_devices else default_device
        if selected is None:
            selected = self.system_audio_devices[0]
        self.selected_system_audio_device = selected
        for idx in range(self.system_audio_device_combo.count()):
            item = self.system_audio_device_combo.itemData(idx)
            if item == selected:
                self.system_audio_device_combo.setCurrentIndex(idx)
                break
        self.system_audio_device_combo.blockSignals(False)
        self.system_audio_enable_checkbox.setEnabled(True)
        self._update_audio_mix_controls(recording=self.recorder is not None and self.recorder.is_recording())

    def _update_audio_mix_controls(self, recording: bool) -> None:
        supports_mix = self._mode_supports_system_audio_mix()
        has_system_devices = bool(self.system_audio_devices)

        self.audio_mix_panel.setVisible(True)
        self.system_audio_enable_checkbox.setEnabled((not recording) and has_system_devices and supports_mix)
        self.mic_volume_slider.setEnabled((not recording) and supports_mix)

        system_controls_enabled = (
            (not recording)
            and supports_mix
            and has_system_devices
            and self.system_audio_enable_checkbox.isChecked()
        )
        self.system_audio_device_combo.setEnabled(system_controls_enabled)
        self.system_audio_volume_slider.setEnabled(system_controls_enabled)

        if not supports_mix:
            self.audio_mix_hint_label.setText("System audio mixing is available only in screen/window/game modes.")
            self.system_audio_value.setText(self._system_audio_summary())
            return
        if not has_system_devices:
            if not self.system_audio_wasapi_supported:
                self.audio_mix_hint_label.setText(
                    "No system audio source detected. Your FFmpeg build does not support WASAPI, "
                    "and no DirectShow loopback device (like Stereo Mix) is available."
                )
            else:
                self.audio_mix_hint_label.setText(
                    "No system audio loopback source detected. "
                    "Enable a loopback device (for example Stereo Mix) in Windows sound settings."
                )
            self.system_audio_value.setText(self._system_audio_summary())
            return
        if not self.system_audio_enabled:
            self.audio_mix_hint_label.setText(f"System audio is off. Mic volume: {self.mic_volume_percent}%.")
            self.system_audio_value.setText(self._system_audio_summary())
            return

        self.audio_mix_hint_label.setText(
            f"Mixing mic ({self.mic_volume_percent}%) and system ({self.system_audio_volume_percent}%)."
        )
        self.system_audio_value.setText(self._system_audio_summary())

    def _update_webcam_controls(self, recording: bool) -> None:
        supports_overlay = self._mode_supports_webcam_overlay()
        has_devices = bool(self.device_lists and self.device_lists.video)

        self.webcam_panel.setVisible(True)
        self.webcam_enable_checkbox.setEnabled((not recording) and has_devices and supports_overlay)

        controls_enabled = (
            (not recording)
            and supports_overlay
            and has_devices
        )
        self.webcam_device_combo.setEnabled(controls_enabled)
        self.webcam_size_slider.setEnabled(controls_enabled)
        self.webcam_position_combo.setEnabled(controls_enabled)

        if not has_devices:
            self.webcam_hint_label.setText("No webcam detected.")
            self._sync_live_webcam_preview()
            return
        if not supports_overlay:
            self.webcam_hint_label.setText("Webcam overlay is available only in screen/window/game modes.")
            self._sync_live_webcam_preview()
            return
        if not self.webcam_enabled:
            self.webcam_hint_label.setText(
                "Webcam overlay is off. You can still choose device, size, and position before enabling it."
            )
            self._sync_live_webcam_preview()
            return
        self.webcam_hint_label.setText(f"Overlay: {self._webcam_summary()}")
        self._sync_live_webcam_preview()

    def _webcam_overlay_for_recording(self) -> WebcamOverlay | None:
        if not self.webcam_enabled or not self._mode_supports_webcam_overlay():
            return None
        if not self.selected_webcam_device:
            raise RuntimeError("Webcam overlay is enabled but no webcam device is selected.")
        return WebcamOverlay(
            device_name=self.selected_webcam_device,
            size_percent=self.webcam_size_percent,
            position=self.webcam_position,
        )

    def _system_audio_for_recording(self) -> tuple[str | None, str | None]:
        if not self.system_audio_enabled or not self._mode_supports_system_audio_mix():
            return (None, None)
        if self.selected_system_audio_device is None:
            raise RuntimeError("System audio is enabled but no system audio device is selected.")
        return (
            self.selected_system_audio_device.kind,
            self.selected_system_audio_device.name,
        )

    def on_encoder_changed(self, text: str) -> None:
        # Encoder is forced to automatic mode.
        self.video_encoder_preference = "auto"
        if text != self._encoder_preference_label():
            self.encoder_combo.blockSignals(True)
            self.encoder_combo.setCurrentText(self._encoder_preference_label())
            self.encoder_combo.blockSignals(False)
        recording = self.recorder is not None and self.recorder.is_recording()
        self._update_video_encoding_controls(recording=recording)
        self._set_controls_for_recording(recording)
        if self.current_section != "home":
            self.section_meta_label.setText(self._section_meta_text(self.current_section))
        self._set_status_chip("good", "Encoder Auto-Detected")

    def on_quality_changed(self, text: str) -> None:
        self.video_quality_preset = self.QUALITY_OPTIONS.get(text, "balanced")
        recording = self.recorder is not None and self.recorder.is_recording()
        self._update_video_encoding_controls(recording=recording)
        self._set_controls_for_recording(recording)
        if self.current_section != "home":
            self.section_meta_label.setText(self._section_meta_text(self.current_section))
        self._set_status_chip("good", "Quality Updated")

    def on_webcam_toggle_changed(self, checked: bool) -> None:
        self.webcam_enabled = checked
        self._update_webcam_controls(recording=self.recorder is not None and self.recorder.is_recording())
        self._set_controls_for_recording(self.recorder is not None and self.recorder.is_recording())
        self._set_status_chip("good", "Webcam Overlay On" if checked else "Webcam Overlay Off")

    def on_webcam_device_changed(self, text: str) -> None:
        cleaned = text.strip()
        if not cleaned or cleaned == "No webcam detected":
            self.selected_webcam_device = None
        else:
            self.selected_webcam_device = cleaned
        self._update_webcam_controls(recording=self.recorder is not None and self.recorder.is_recording())

    def on_webcam_size_changed(self, value: int) -> None:
        self.webcam_size_percent = int(value)
        self.webcam_size_value_label.setText(f"{self.webcam_size_percent}%")
        self._update_webcam_controls(recording=self.recorder is not None and self.recorder.is_recording())

    def on_webcam_position_changed(self, text: str) -> None:
        self.webcam_position = self.WEBCAM_POSITIONS.get(text, "bottom_right")
        self._update_webcam_controls(recording=self.recorder is not None and self.recorder.is_recording())

    def on_system_audio_toggle_changed(self, checked: bool) -> None:
        self.system_audio_enabled = checked
        recording = self.recorder is not None and self.recorder.is_recording()
        self._update_audio_mix_controls(recording=recording)
        self._set_controls_for_recording(recording)
        self._set_status_chip("good", "System Audio On" if checked else "System Audio Off")

    def on_system_audio_device_changed(self, _index: int) -> None:
        data = self.system_audio_device_combo.currentData()
        if isinstance(data, SystemAudioDevice):
            self.selected_system_audio_device = data
        else:
            self.selected_system_audio_device = None
        self._update_audio_mix_controls(recording=self.recorder is not None and self.recorder.is_recording())

    def on_mic_volume_changed(self, value: int) -> None:
        self.mic_volume_percent = int(value)
        self.mic_volume_value_label.setText(f"{self.mic_volume_percent}%")
        self._update_audio_mix_controls(recording=self.recorder is not None and self.recorder.is_recording())

    def on_system_audio_volume_changed(self, value: int) -> None:
        self.system_audio_volume_percent = int(value)
        self.system_audio_volume_value_label.setText(f"{self.system_audio_volume_percent}%")
        self._update_audio_mix_controls(recording=self.recorder is not None and self.recorder.is_recording())

    def _set_capture_mode(self, mode_key: str, announce: bool = True) -> None:
        if mode_key not in self.ALL_MODES:
            return
        self.current_mode = mode_key

        descriptions = {
            "region": ("Rectangle area mode selected", "Screen Recording - Rectangle area mode captures only your selected region."),
            "fullscreen": ("Fullscreen mode selected", "Screen Recording - Fullscreen mode captures the entire desktop area."),
            "window": ("Specific window mode selected", "Screen Recording - Specific window mode captures only the selected app window."),
            "device": ("Device recording mode selected", "Device Recording - Capture from camera, capture card, or other video input device."),
            "game": ("Game recording mode selected", "Game Recording - Capture the selected game window with 60 fps settings."),
            "audio": ("Audio-only mode selected", "Audio Recording - Capture selected audio device without video."),
        }
        hint, desc = descriptions[mode_key]
        self.hint_label.setText(hint)
        self.mode_description_label.setText(desc)
        self.capture_mode_value.setText(self._capture_mode_summary())
        self.source_value.setText(self._source_summary())
        self._update_mode_selection()
        recording = self.recorder is not None and self.recorder.is_recording()
        self._update_mode_action_buttons(recording)
        self._set_controls_for_recording(recording)
        if announce and mode_key in {"window", "device", "game", "audio"}:
            self._set_status_chip("good", "Configure Source")

    def _update_mode_selection(self) -> None:
        for key, tile in self.mode_tiles.items():
            tile.setChecked(key == self.current_mode)
            tile.setProperty("active", "true" if key == self.current_mode else "false")
            self._repolish(tile)
        for key, button in self.toolbar_mode_buttons.items():
            button.setChecked(key == self.current_mode)
            button.setProperty("active", "true" if key == self.current_mode else "false")
            self._repolish(button)

    def _update_mode_action_buttons(self, recording: bool) -> None:
        is_region = self.current_mode == "region"
        needs_source = self.current_mode in {"window", "device", "game", "audio"}
        self.select_region_button.setVisible(is_region)
        self.clear_region_button.setVisible(is_region)
        self.select_source_button.setVisible(needs_source)
        self.clear_source_button.setVisible(needs_source)
        source_text = {
            "window": "Select Window",
            "device": "Select Device",
            "game": "Select Game Window",
            "audio": "Select Audio Source",
        }.get(self.current_mode, "Select Source")
        self.select_source_button.setText(source_text)
        self.select_region_button.setEnabled(is_region and not recording)
        self.clear_region_button.setEnabled(is_region and not recording)
        self.select_source_button.setEnabled(needs_source and not recording)
        self.clear_source_button.setEnabled(needs_source and not recording)
        self.sync_test_button.setVisible(True)
        self.sync_test_button.setEnabled((not recording) and self.ff.found)
        self._update_video_encoding_controls(recording)
        self._update_webcam_controls(recording)
        self._update_audio_mix_controls(recording)

    def _can_start_current_mode(self) -> bool:
        if self.recorder is None or not self.ff.found:
            return False
        if self.webcam_enabled and self._mode_supports_webcam_overlay():
            if not self.selected_webcam_device:
                return False
        if self.system_audio_enabled and self._mode_supports_system_audio_mix():
            if self.selected_system_audio_device is None:
                return False
        if self.current_mode in {"region", "fullscreen", "window", "game"}:
            return self.mic_name is not None
        if self.current_mode == "device":
            return bool(self.selected_device_video)
        if self.current_mode == "audio":
            return bool(self.selected_audio_source or self.mic_name)
        return False

    def _can_take_screenshot(self) -> bool:
        if not self.ff.found:
            return False
        return self.current_mode != "audio"

    def refresh_status(self) -> None:
        self.output_path_value.setText(str(self.paths.recordings_dir))
        self.capture_mode_value.setText(self._capture_mode_summary())
        self.region_value.setText(self._region_summary())
        self.output_hint_label.setText(f"Save: {self.paths.recordings_dir}")
        if self.current_home_tab in {"videos", "images", "audios"}:
            self._refresh_library_tab(self.current_home_tab)

        self.ff = detect_ffmpeg()
        if not self.ff.found:
            self.ffmpeg_value.setText("Unavailable")
            self.mic_value.setText("Unavailable")
            self.source_value.setText("Unavailable")
            self.system_audio_value.setText("Unavailable")
            self.system_audio_wasapi_supported = False
            self.h264_encoder_support = None
            self.device_lists = None
            self._sync_webcam_devices([])
            self._sync_system_audio_devices([])
            self._set_status_chip("warn", "Setup Required")
            self.record_button.setEnabled(False)
            self.stop_button.setEnabled(False)
            self.screenshot_button.setEnabled(False)
            self._update_video_encoding_controls(recording=False)
            return

        self.ffmpeg_value.setText(self.ff.version or self.ff.path or "Detected")
        if self.recorder is None or not self.recorder.is_recording():
            self.recorder = RecorderController(
                ffmpeg_path=self.ff.path,
                recordings_dir=self.paths.recordings_dir,
                temp_dir=self.paths.temp_dir,
            )
        self._refresh_h264_encoder_support(refresh=True)

        try:
            devices = list_dshow_devices(self.ff.path)
            self.device_lists = devices
            self.system_audio_wasapi_supported = supports_wasapi_loopback(self.ff.path)
            self.mic_name = pick_default_mic(devices.audio)
            self.mic_value.setText(self.mic_name or "Not detected")

            if self.selected_audio_source is None and self.mic_name:
                self.selected_audio_source = self.mic_name
            if self.selected_device_video is None and devices.video:
                self.selected_device_video = devices.video[0]
            if self.selected_device_audio is None and devices.audio:
                self.selected_device_audio = devices.audio[0]
            self._sync_webcam_devices(devices.video)
            self._sync_system_audio_devices(devices.system_audio)

            if self._can_start_current_mode():
                self._set_status_chip("good", "Ready")
            else:
                self._set_status_chip("warn", "Source Required")
        except Exception:
            self.device_lists = None
            self.mic_name = None
            self.system_audio_wasapi_supported = False
            self.mic_value.setText("Device detection failed")
            self._sync_webcam_devices([])
            self._sync_system_audio_devices([])
            self._set_status_chip("error", "Device Error")

        self.source_value.setText(self._source_summary())
        if self.current_section != "home":
            self.section_meta_label.setText(self._section_meta_text(self.current_section))
        recording = self.recorder is not None and self.recorder.is_recording()
        self._set_controls_for_recording(recording)

    def _set_controls_for_recording(self, recording: bool) -> None:
        self.record_button.setEnabled((not recording) and self._can_start_current_mode())
        self.stop_button.setEnabled(recording)
        self.change_recordings_button.setEnabled(not recording)
        self.screenshot_button.setEnabled((not recording) and self._can_take_screenshot())
        for tile in self.mode_tiles.values():
            tile.setEnabled(not recording)
        for button in self.toolbar_mode_buttons.values():
            button.setEnabled(not recording)
        self._update_mode_action_buttons(recording)
        self._set_rec_indicator(recording)

    def _pick_from_list(
        self,
        title: str,
        label: str,
        options: list[str],
        default_value: str | None = None,
    ) -> str | None:
        if not options:
            return None
        index = 0
        if default_value and default_value in options:
            index = options.index(default_value)
        value, ok = QInputDialog.getItem(self, title, label, options, index, False)
        if not ok:
            return None
        selected = value.strip()
        return selected or None

    def _choose_window(self, for_game: bool) -> str | None:
        windows = list_visible_window_titles()
        if not windows:
            QMessageBox.warning(self, "CAPTRIX", "No capturable windows found.")
            return None

        default = self.selected_game_window_title if for_game else self.selected_window_title
        fg = get_foreground_window_title()
        if fg and fg in windows:
            default = fg

        label = "Select game window" if for_game else "Select window"
        return self._pick_from_list("CAPTRIX", label, windows, default_value=default)

    def _ensure_device_lists(self) -> DeviceLists | None:
        if not self.ff.found:
            QMessageBox.warning(self, "CAPTRIX", "FFmpeg is not ready.")
            return None
        try:
            devices = list_dshow_devices(self.ff.path)
            self.device_lists = devices
            self.system_audio_wasapi_supported = supports_wasapi_loopback(self.ff.path)
            self._sync_webcam_devices(devices.video)
            self._sync_system_audio_devices(devices.system_audio)
            return devices
        except Exception as e:
            self.system_audio_wasapi_supported = False
            self._sync_webcam_devices([])
            self._sync_system_audio_devices([])
            QMessageBox.critical(self, "CAPTRIX", f"Failed to list capture devices:\n{e}")
            return None

    def on_select_source_clicked(self) -> None:
        if self.recorder and self.recorder.is_recording():
            QMessageBox.warning(self, "CAPTRIX", "Stop the current recording before changing source.")
            return

        if self.current_mode == "window":
            selected = self._choose_window(for_game=False)
            if selected:
                self.selected_window_title = selected
        elif self.current_mode == "game":
            selected = self._choose_window(for_game=True)
            if selected:
                self.selected_game_window_title = selected
        elif self.current_mode == "device":
            devices = self._ensure_device_lists()
            if not devices:
                return
            if not devices.video:
                QMessageBox.warning(self, "CAPTRIX", "No video capture devices found.")
                return

            video = self._pick_from_list("CAPTRIX", "Select video device", devices.video, self.selected_device_video)
            if not video:
                return

            audio_options = ["(No audio)"] + devices.audio
            audio = self._pick_from_list(
                "CAPTRIX",
                "Select audio device",
                audio_options,
                self.selected_device_audio or "(No audio)",
            )
            if audio is None:
                return
            self.selected_device_video = video
            self.selected_device_audio = None if audio == "(No audio)" else audio
        elif self.current_mode == "audio":
            devices = self._ensure_device_lists()
            if not devices:
                return

            options = list(dict.fromkeys([*devices.audio, *([self.mic_name] if self.mic_name else [])]))
            options = [o for o in options if o]
            if not options:
                QMessageBox.warning(self, "CAPTRIX", "No audio source available.")
                return

            audio = self._pick_from_list("CAPTRIX", "Select audio source", options, self.selected_audio_source)
            if audio:
                self.selected_audio_source = audio

        self.source_value.setText(self._source_summary())
        self._set_controls_for_recording(False)
        self._set_status_chip("good", "Source Updated")

    def on_clear_source_clicked(self) -> None:
        if self.recorder and self.recorder.is_recording():
            QMessageBox.warning(self, "CAPTRIX", "Stop the current recording before clearing source.")
            return

        if self.current_mode == "window":
            self.selected_window_title = None
        elif self.current_mode == "game":
            self.selected_game_window_title = None
        elif self.current_mode == "device":
            self.selected_device_video = None
            self.selected_device_audio = None
        elif self.current_mode == "audio":
            self.selected_audio_source = None

        self.source_value.setText(self._source_summary())
        self._set_controls_for_recording(False)
        self._set_status_chip("good", "Source Cleared")

    def on_change_recordings_clicked(self) -> None:
        if self.recorder and self.recorder.is_recording():
            QMessageBox.warning(
                self,
                "CAPTRIX",
                "Stop the current recording before changing the recordings folder.",
            )
            return

        selected = QFileDialog.getExistingDirectory(
            self,
            "Select Recordings Folder",
            str(self.paths.recordings_dir),
            QFileDialog.Option.ShowDirsOnly,
        )
        if not selected:
            return

        try:
            self.paths = set_recordings_dir(selected, app_name="CAPTRIX")
            self.refresh_status()
            QMessageBox.information(self, "CAPTRIX", f"Recordings folder updated:\n{self.paths.recordings_dir}")
        except Exception as e:
            QMessageBox.critical(self, "CAPTRIX", f"Failed to update recordings folder:\n{e}")

    def on_select_region_clicked(self) -> None:
        if self.recorder and self.recorder.is_recording():
            QMessageBox.warning(
                self,
                "CAPTRIX",
                "Stop the current recording before selecting a region.",
            )
            return

        selected = select_region(self)
        if selected is None:
            return

        self.selected_region = selected
        self.region_value.setText(self._region_summary())
        self._set_capture_mode("region", announce=False)
        self._set_status_chip("good", "Region Selected")

    def on_clear_region_clicked(self) -> None:
        if self.recorder and self.recorder.is_recording():
            QMessageBox.warning(
                self,
                "CAPTRIX",
                "Stop the current recording before clearing the region.",
            )
            return

        self.selected_region = None
        self.region_value.setText(self._region_summary())
        self._set_status_chip("good", "Ready")

    def on_take_screenshot_clicked(self) -> None:
        if self.recorder and self.recorder.is_recording():
            QMessageBox.warning(
                self,
                "CAPTRIX",
                "Stop the current recording before taking a screenshot.",
            )
            return

        if not self.ff.found:
            QMessageBox.warning(self, "CAPTRIX", "FFmpeg is not ready.")
            return

        if not self.recorder:
            self.recorder = RecorderController(
                ffmpeg_path=self.ff.path,
                recordings_dir=self.paths.recordings_dir,
                temp_dir=self.paths.temp_dir,
            )

        try:
            if self.current_mode == "region":
                if self.selected_region is None:
                    self.on_select_region_clicked()
                    if self.selected_region is None:
                        return
                path = self.recorder.take_screenshot_fullscreen(
                    region=self.selected_region,
                    region_mode=self.region_mode,
                )
            elif self.current_mode == "fullscreen":
                path = self.recorder.take_screenshot_fullscreen(
                    region=None,
                    region_mode=self.region_mode,
                )
            elif self.current_mode == "window":
                if not self.selected_window_title:
                    self.on_select_source_clicked()
                    if not self.selected_window_title:
                        return
                path = self.recorder.take_screenshot_window(self.selected_window_title)
            elif self.current_mode == "game":
                if not self.selected_game_window_title:
                    self.on_select_source_clicked()
                    if not self.selected_game_window_title:
                        return
                path = self.recorder.take_screenshot_window(self.selected_game_window_title)
            elif self.current_mode == "device":
                if not self.selected_device_video:
                    self.on_select_source_clicked()
                    if not self.selected_device_video:
                        return
                path = self.recorder.take_screenshot_device(self.selected_device_video)
            else:
                QMessageBox.warning(
                    self,
                    "CAPTRIX",
                    "Screenshot is unavailable in audio-only mode.",
                )
                return

            if self.current_home_tab in {"videos", "images", "audios"}:
                self._refresh_library_tab(self.current_home_tab)
            self._set_status_chip("good", "Screenshot Saved")
            QMessageBox.information(self, "CAPTRIX", f"Screenshot saved:\n{path}")
        except Exception as e:
            self._set_status_chip("error", "Screenshot Failed")
            QMessageBox.critical(self, "CAPTRIX", f"Failed to take screenshot:\n{e}")

    def on_generate_sync_test_clicked(self) -> None:
        if self.recorder and self.recorder.is_recording():
            QMessageBox.warning(
                self,
                "CAPTRIX",
                "Stop the current recording before generating a sync test clip.",
            )
            return

        if not self.ff.found:
            QMessageBox.warning(self, "CAPTRIX", "FFmpeg is not ready.")
            return

        if not self.recorder:
            self.recorder = RecorderController(
                ffmpeg_path=self.ff.path,
                recordings_dir=self.paths.recordings_dir,
                temp_dir=self.paths.temp_dir,
            )

        try:
            path = self.recorder.generate_sync_test_clip(duration_sec=8, fps=30)
            if self.current_home_tab in {"videos", "images", "audios"}:
                self._refresh_library_tab(self.current_home_tab)
            self._set_status_chip("good", "Sync Test Ready")
            QMessageBox.information(
                self,
                "CAPTRIX",
                "Sync test clip generated.\n"
                "Use it to verify flash and beep alignment.\n\n"
                f"File:\n{path}",
            )
        except Exception as e:
            self._set_status_chip("error", "Sync Test Failed")
            QMessageBox.critical(self, "CAPTRIX", f"Failed to generate sync test clip:\n{e}")

    def _set_webcam_overlay_enabled(self, enabled: bool) -> None:
        self.webcam_enable_checkbox.blockSignals(True)
        self.webcam_enable_checkbox.setChecked(enabled)
        self.webcam_enable_checkbox.blockSignals(False)
        self.webcam_enabled = enabled
        self._update_webcam_controls(recording=self.recorder is not None and self.recorder.is_recording())

    def _start_recording_for_current_mode(
        self,
        webcam_overlay: WebcamOverlay | None,
        system_audio_kind: str | None,
        system_audio_device: str | None,
    ) -> None:
        if self.recorder is None:
            raise RuntimeError("Recorder not ready.")

        if self.current_mode == "region":
            if self.selected_region is None:
                self.on_select_region_clicked()
                if self.selected_region is None:
                    return
            if not self.mic_name:
                raise RuntimeError("No microphone detected.")
            self.recorder.start_recording_windows_fullscreen_mic(
                self.mic_name,
                region=self.selected_region,
                region_mode=self.region_mode,
                webcam_overlay=webcam_overlay,
                system_audio_device=system_audio_device,
                system_audio_kind=system_audio_kind,
                mic_volume_percent=self.mic_volume_percent,
                system_audio_volume_percent=self.system_audio_volume_percent,
                encoder_preference=self.video_encoder_preference,
                quality_preset=self.video_quality_preset,
            )
            return

        if self.current_mode == "fullscreen":
            if not self.mic_name:
                raise RuntimeError("No microphone detected.")
            self.recorder.start_recording_windows_fullscreen_mic(
                self.mic_name,
                region=None,
                region_mode=self.region_mode,
                webcam_overlay=webcam_overlay,
                system_audio_device=system_audio_device,
                system_audio_kind=system_audio_kind,
                mic_volume_percent=self.mic_volume_percent,
                system_audio_volume_percent=self.system_audio_volume_percent,
                encoder_preference=self.video_encoder_preference,
                quality_preset=self.video_quality_preset,
            )
            return

        if self.current_mode == "window":
            if not self.mic_name:
                raise RuntimeError("No microphone detected.")
            if not self.selected_window_title:
                self.on_select_source_clicked()
                if not self.selected_window_title:
                    return
            self.recorder.start_recording_window_mic(
                self.mic_name,
                self.selected_window_title,
                webcam_overlay=webcam_overlay,
                system_audio_device=system_audio_device,
                system_audio_kind=system_audio_kind,
                mic_volume_percent=self.mic_volume_percent,
                system_audio_volume_percent=self.system_audio_volume_percent,
                encoder_preference=self.video_encoder_preference,
                quality_preset=self.video_quality_preset,
            )
            return

        if self.current_mode == "device":
            if not self.selected_device_video:
                self.on_select_source_clicked()
                if not self.selected_device_video:
                    return
            self.recorder.start_recording_device(
                video_device=self.selected_device_video,
                audio_device=self.selected_device_audio,
                encoder_preference=self.video_encoder_preference,
                quality_preset=self.video_quality_preset,
            )
            return

        if self.current_mode == "game":
            if not self.mic_name:
                raise RuntimeError("No microphone detected.")
            if not self.selected_game_window_title:
                self.on_select_source_clicked()
                if not self.selected_game_window_title:
                    return
            self.recorder.start_recording_game_window_mic(
                self.mic_name,
                self.selected_game_window_title,
                webcam_overlay=webcam_overlay,
                system_audio_device=system_audio_device,
                system_audio_kind=system_audio_kind,
                mic_volume_percent=self.mic_volume_percent,
                system_audio_volume_percent=self.system_audio_volume_percent,
                encoder_preference=self.video_encoder_preference,
                quality_preset=self.video_quality_preset,
            )
            return

        if self.current_mode == "audio":
            source = self.selected_audio_source or self.mic_name
            if not source:
                self.on_select_source_clicked()
                source = self.selected_audio_source or self.mic_name
                if not source:
                    return
            self.recorder.start_recording_audio_only(source)
            return

        raise RuntimeError(f"Unsupported mode: {self.current_mode}")

    def on_start_recording_clicked(self) -> None:
        if not self.recorder:
            QMessageBox.warning(self, "CAPTRIX", "Recorder not ready.")
            return

        try:
            # Release Qt camera handle before FFmpeg opens the webcam device.
            had_preview_camera = self.webcam_preview_overlay.camera is not None
            self.webcam_preview_overlay.stop_preview()
            if had_preview_camera:
                QApplication.processEvents()
                time.sleep(1.10)
            webcam_overlay = self._webcam_overlay_for_recording()
            system_audio_kind, system_audio_device = self._system_audio_for_recording()
            try:
                self._start_recording_for_current_mode(
                    webcam_overlay=webcam_overlay,
                    system_audio_kind=system_audio_kind,
                    system_audio_device=system_audio_device,
                )
            except WebcamInputError as webcam_error:
                if webcam_overlay is None:
                    raise
                self._set_webcam_overlay_enabled(False)
                self._start_recording_for_current_mode(
                    webcam_overlay=None,
                    system_audio_kind=system_audio_kind,
                    system_audio_device=system_audio_device,
                )
                self._set_controls_for_recording(True)
                self._set_status_chip("live", "Recording (Webcam Off)")
                QMessageBox.warning(
                    self,
                    "CAPTRIX",
                    "Webcam overlay failed to start and was disabled for this recording.\n"
                    "Recording has started without webcam overlay.\n\n"
                    f"Details:\n{webcam_error}",
                )
                return

            self._set_controls_for_recording(True)
            self._set_status_chip("live", "Recording")
        except Exception as e:
            self._set_status_chip("error", "Start Failed")
            self._set_controls_for_recording(False)
            self._sync_live_webcam_preview()
            QMessageBox.critical(self, "CAPTRIX", f"Failed to start recording:\n{e}")

    def on_stop_recording_clicked(self) -> None:
        if not self.recorder:
            return

        self._set_status_chip("busy", "Finalizing")
        try:
            result = self.recorder.stop_recording()
            self._set_controls_for_recording(False)
            msg = QMessageBox(self)
            msg.setWindowTitle("CAPTRIX")
            msg.setIcon(QMessageBox.Icon.Information)
            msg.setText("Recording saved.")
            msg.setInformativeText(f"Output file:\n{result.mp4_path}")
            open_folder_button = msg.addButton("Open Folder", QMessageBox.ButtonRole.ActionRole)
            msg.addButton(QMessageBox.StandardButton.Ok)
            msg.exec()
            if msg.clickedButton() is open_folder_button:
                self._open_recordings_folder()
            self.refresh_status()
            self._sync_live_webcam_preview()
        except Exception as e:
            QMessageBox.critical(self, "CAPTRIX", f"Failed to stop recording:\n{e}")
            self._set_status_chip("error", "Stop Failed")
            self._set_controls_for_recording(False)
            self._sync_live_webcam_preview()

    def closeEvent(self, event) -> None:  # type: ignore[override]
        if self.recorder is not None and self.recorder.is_recording():
            answer = QMessageBox.question(
                self,
                "CAPTRIX",
                "Recording is in progress. Stop and finalize before exit?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes,
            )
            if answer == QMessageBox.StandardButton.Yes:
                try:
                    self.recorder.stop_recording()
                except Exception as e:
                    fallback = QMessageBox.question(
                        self,
                        "CAPTRIX",
                        "Failed to finalize recording before exit.\n"
                        "You can recover this temp session on next startup.\n\n"
                        f"Error:\n{e}\n\n"
                        "Exit anyway?",
                        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                        QMessageBox.StandardButton.No,
                    )
                    if fallback != QMessageBox.StandardButton.Yes:
                        event.ignore()
                        return
            else:
                event.ignore()
                return

        try:
            self.webcam_preview_overlay.stop_preview()
            self.webcam_preview_overlay.close()
        except Exception:
            pass
        super().closeEvent(event)
