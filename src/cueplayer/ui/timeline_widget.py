"""Timeline canvas: detailed waveform + video lane + mark lanes + optional auto-scroll."""

from __future__ import annotations

import math
from pathlib import Path
from time import monotonic_ns

import numpy as np
from PySide6.QtCore import QPointF, QRect, QRectF, QSize, Qt, QTimer, Signal, QEvent
from PySide6.QtGui import (
    QColor,
    QCursor,
    QDragEnterEvent,
    QDragMoveEvent,
    QDropEvent,
    QFont,
    QInputDevice,
    QKeyEvent,
    QPainter,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import QInputDialog, QLabel, QMenu, QSlider, QWidget

from cueplayer.domain.models import MarkLineStyle, Song, VideoClip
from cueplayer.media.audio_loader import AudioBuffer, choose_peak_level
from cueplayer.media.video_clip_waveform import (
    VideoClipWaveformCache,
    sample_source_peaks_for_clip_times,
    sample_source_raw_for_clip_times,
    timeline_to_clip_local,
)
from cueplayer.ui.drag_drop import (
    accept_file_drag,
    accept_file_drop,
    mime_looks_like_file_drop,
    video_paths_from_mime,
)
from cueplayer.ui.icon_button import IconButton
from cueplayer.ui.marker_draw import draw_marker_shape
from cueplayer.ui.theme import ACCENT, ACCENT_HOVER, BG_APP, COLOR_VIDEO, SLIDER_QSS, WARNING, with_alpha
from cueplayer.ui.video_clip_edit import (
    clip_duration_after_right_trim,
    clip_start_after_body_drag,
)
from cueplayer.ui.song_edit_dialog import format_setlist_number

from cueplayer.media.video_loader import STILL_IMAGE_SUFFIXES

_VIDEO_SUFFIXES = {".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v"} | set(STILL_IMAGE_SUFFIXES)


class TimelineWidget(QWidget):
    seek_requested = Signal(float)
    scrub_started = Signal()
    scrub_ended = Signal()
    # Mid-scrub Preview/Clean update (local playhead time). Does not move
    # the audio engine — that stays on seek_requested (press + release).
    scrub_preview_requested = Signal(float)
    selection_changed = Signal(list)  # list[str] mark ids
    delete_requested = Signal(list)  # list[str] mark ids
    marks_changed = Signal()
    marks_moved = Signal(object)  # dict[str, tuple[float, float]]
    offset_requested = Signal(list, float)  # mark ids, delta seconds
    loop_changed = Signal(object, object)  # loop_a, loop_b
    auto_scroll_changed = Signal(bool)

    # Video clip lane.
    video_clip_selection_changed = Signal(list)  # list[str] clip ids
    video_clips_changed = Signal()  # structural change (lock/hide toggle etc.) — mark dirty + resync
    video_clip_edited = Signal(str, tuple, tuple)  # clip id, old (start,in,dur), new (start,in,dur)
    video_clips_batch_edited = Signal(object)  # dict[str, tuple[tuple, tuple]] — quick-nudge menu
    delete_video_clips_requested = Signal(list)  # list[str] clip ids
    add_video_clip_requested = Signal(float)  # timeline seconds to add at
    split_video_clip_requested = Signal(str, float)  # clip id, split time
    duplicate_video_clip_requested = Signal(str)  # clip id
    video_files_dropped = Signal(list, float)  # paths, drop time seconds
    video_track_mute_toggled = Signal(bool)
    video_track_visibility_changed = Signal(bool)  # show_video_track
    wave_gain_line_visibility_changed = Signal(bool)
    ltc_gain_line_visibility_changed = Signal(bool)
    ltc_track_visibility_changed = Signal(bool)  # show_ltc_track
    content_geometry_changed = Signal()  # min/content height changed — parent scroll area should resize widget
    view_changed = Signal()  # scroll / zoom / playhead — overview navigator should refresh
    video_clip_volume_changed = Signal(str, float)  # clip id, new volume 0..1
    music_volume_changed = Signal(float)  # new music-bed volume 0..1 (Video/Music balance)
    audio_gain_changed = Signal(float)  # per-file gain in dB (-12..+12)
    lane_name_changed = Signal(int, str)  # lane_index, new name
    mark_manager_requested = Signal()
    mark_lane_height_changed = Signal(float)
    mark_track_colors_changed = Signal(bool)
    add_mark_requested = Signal(int)  # lane_index at current playhead
    # Internal: video waveform decode finished (may be emitted from a worker).
    _video_waveforms_ready = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._song: Song | None = None
        self._audio: AudioBuffer | None = None
        self._ltc_audio: AudioBuffer | None = None
        self._ltc_channel: int | None = None
        self._audio_loading = False
        self._audio_loading_label = ""
        self._position = 0.0
        self._pixels_per_second = 120.0
        self._scroll_x = 0.0
        self._scroll_y = 0.0
        self._content_height = 0
        self._auto_scroll = True
        self._header_width = 140
        self._ruler_height = 28
        self._wave_height = 220
        self._lane_height = 28
        self._project_mark_lane_height = 28.0
        self._show_mark_track_colors = True
        self._video_lane_base_height = 40.0
        self._video_lane_min_height = 28.0
        self._video_lane_split_hit = 6
        # Show-eye sits on the waveform bottom edge in the header (no extra lane height).
        self._video_header_eye_row_height = 0.0
        # Expanded Video chrome shows the per-clip volume fader only.
        self._video_expand_extra = 42.0
        self._video_track_expanded = False
        self._video_track_muted = False
        self._show_video_track = True
        # Music header expand: Music bed % + waveform gain (dB) — no Video eye required.
        self._music_expand_extra = 96.0
        self._music_header_expanded = False
        self._ltc_lane_height = 56.0
        self._ltc_lane_min_height = 28.0
        self._ltc_waveform_color = WARNING
        self._selected_clip_ids: set[str] = set()
        self._hover_clip_id: str | None = None
        self._dragging_clip: str | None = None
        self._trimming_clip: tuple[str, str] | None = None  # (clip_id, "left" | "right")
        self._clip_drag_snapshot: dict[str, tuple[float, float, float]] = {}
        self._clip_drag_origin_x = 0.0
        self._clip_drag_moved = False
        self._video_gesture_active = False
        self._clip_edge_hit = 8.0
        self._show_mark_tracks = True
        self._show_mark_stem = False
        self._mark_line_style: MarkLineStyle = "solid"
        self._mark_dash_on = 4.0
        self._mark_dash_off = 4.0
        self._mark_line_width = 1.0
        self._waveform_color = "#3dd68c"
        self._playhead_color = "#ff5a5f"
        self._loop_a: float | None = None
        self._loop_b: float | None = None
        self._loop_enabled = False
        self._dragging_loop: str | None = None  # "a" | "b"
        self._loop_drag_moved = False
        self._loop_drag_origin_x = 0.0
        self._hover_loop: str | None = None
        self._scrubbing = False
        self._resizing_wave = False
        self._resizing_video_lane = False
        self._resizing_mark_lanes = False
        self._mark_lane_split_h = 6
        self._mark_lane_split_hit = 6
        self._geometry_sync_pending = False
        self._wave_split_hover = False
        self._video_lane_split_hover = False
        self._mark_lane_split_hover = False
        self._show_mark_lane_resize_bar = True
        self._show_wave_gain_line = False
        self._show_ltc_gain_line = False
        self._dragging_audio_gain = False
        self._audio_gain_zone: str | None = None  # "wave" | "ltc"
        self._audio_gain_drag_bounds: tuple[float, float] | None = None
        self._audio_gain_hit_px = 6
        self._audio_gain_travel_span = 0.9
        self._hover_audio_gain_zone: str | None = None
        self._hover_mark_id: str | None = None
        self._hover_mark_lane_header: int | None = None
        # After a click-seek, keep the view where you clicked until wheel or Auto Scroll.
        self._view_pinned = False
        self._scrub_edge = 64.0
        self._wave_split_hit = 6
        self._last_scrub_preview_ms = 0
        self._selected_mark_ids: set[str] = set()
        self._box_selecting = False
        self._box_additive = False
        self._box_origin = QPointF()
        self._box_current = QPointF()
        self._box_base_ids: set[str] = set()
        self._dragging_marks = False
        self._drag_moved = False
        self._drag_ids: set[str] = set()
        self._drag_start_times: dict[str, float] = {}
        self._drag_origin_x = 0.0
        self._drag_click_seek: float | None = None
        # Plain click on one mark inside a multi-selection → collapse to that mark on release.
        self._pending_single_select: str | None = None
        self._mark_hit_radius = 10.0
        # Pixels of movement before a press becomes a real drag (avoids tiny jitter moves).
        self._drag_slop = 10.0
        self._panning = False
        self._pan_origin_x = 0.0
        self._pan_origin_scroll = 0.0
        self._pan_moved = False
        self._pan_click_seek: float | None = None
        self._box_select_mode = False
        self._setup_mode = False
        self._playing = False
        self._video_waveform_pending_refresh = False
        self._last_play_repaint_ns = 0
        self._play_repaint_interval_ns = 33_000_000  # ~30 Hz — enough for smooth playhead
        self._scrub_backdrop: QPixmap | None = None
        self._scrub_backdrop_scroll = 0.0
        self._scrub_backdrop_pps = 0.0
        self._scrub_backdrop_size = QSize()
        self._scrub_backdrop_overscan = 0
        # When rebuilding a wide play-cache, paint as if the widget were wider.
        self._paint_width_override: int | None = None
        self._box_click_seek: float | None = None
        self._scrub_timer = QTimer(self)
        self._scrub_timer.setInterval(33)
        self._scrub_timer.timeout.connect(self._scrub_tick)
        self._apply_layout_heights()
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAcceptDrops(True)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_context_menu)
        self.setStyleSheet(f"background: {BG_APP};")
        self.setCursor(Qt.CursorShape.ArrowCursor)
        self._build_zoom_overlay()
        self._build_video_track_overlay()
        self._video_waveform_cache = VideoClipWaveformCache()
        self._video_waveform_cache.set_on_ready(self._on_video_waveform_ready)
        # Queued when the worker thread emits — never touch Qt from that thread.
        self._video_waveforms_ready.connect(
            self._apply_video_waveform_ready,
            Qt.ConnectionType.QueuedConnection,
        )
        self.video_clips_changed.connect(self.refresh_video_clip_waveforms)
        self._register_drop_forwarding_children()

    def _register_drop_forwarding_children(self) -> None:
        """Overlay buttons/sliders sit on top of the lane — forward Explorer drops."""
        for child in self.findChildren(QWidget):
            if child is self:
                continue
            child.setAcceptDrops(True)
            child.installEventFilter(self)

    def eventFilter(self, watched, event) -> bool:  # noqa: N802, ANN001
        if watched is not self and self.isAncestorOf(watched):
            et = event.type()
            if et == QEvent.Type.DragEnter:
                self.dragEnterEvent(event)
                return True
            if et == QEvent.Type.DragMove:
                self.dragMoveEvent(event)
                return True
            if et == QEvent.Type.Drop:
                self.dropEvent(event)
                return True
        return super().eventFilter(watched, event)

    def _build_zoom_overlay(self) -> None:
        """Floating controls: edit modes top-left, zoom tools top-right."""
        btn_size = QSize(30, 26)
        self.setup_button = IconButton(
            "letter_s", "Setup (enable to drag Marks)", self, size=btn_size, overlay=True
        )
        self.box_select_button = IconButton(
            "marquee", "Box-select mode (enable to drag-select Marks with left click)", self, size=btn_size, overlay=True
        )
        self.auto_scroll_button = IconButton(
            "letter_a",
            "Auto Scroll — follow the playhead (on when highlighted)",
            self,
            size=btn_size,
            overlay=True,
        )
        self.zoom_out_button = IconButton(
            "zoom_out", "Zoom out (mouse wheel also works)", self, size=btn_size, overlay=True
        )
        self.zoom_in_button = IconButton(
            "zoom_in", "Zoom in (mouse wheel also works)", self, size=btn_size, overlay=True
        )
        self.fit_button = IconButton(
            "fit", "Fit whole song to view", self, size=btn_size, overlay=True
        )
        self.setup_button.set_active(self._setup_mode)
        self.box_select_button.set_active(self._box_select_mode)
        self._sync_auto_scroll_button()
        self.setup_button.clicked.connect(self._toggle_setup_mode)
        self.box_select_button.clicked.connect(self._toggle_box_select_mode)
        self.auto_scroll_button.clicked.connect(self._toggle_auto_scroll_button)
        self.zoom_out_button.clicked.connect(lambda: self.zoom_by(1 / 1.15))
        self.zoom_in_button.clicked.connect(lambda: self.zoom_by(1.15))
        self.fit_button.clicked.connect(self.fit_to_view)
        for btn in (
            self.setup_button,
            self.box_select_button,
            self.auto_scroll_button,
            self.zoom_out_button,
            self.zoom_in_button,
            self.fit_button,
        ):
            btn.raise_()
        self._layout_zoom_overlay()

    def _layout_zoom_overlay(self) -> None:
        if not hasattr(self, "fit_button"):
            return
        margin = 8
        gap = 4
        y = self._ruler_height + 6

        # Left: Setup + box-select (edit modes).
        left_buttons = (self.setup_button, self.box_select_button)
        x = self._header_width + margin
        for btn in left_buttons:
            btn.move(x, y)
            btn.raise_()
            x += btn.width() + gap

        # Right: Auto Scroll + zoom tools.
        right_buttons = (
            self.auto_scroll_button,
            self.zoom_out_button,
            self.zoom_in_button,
            self.fit_button,
        )
        total_w = sum(b.width() for b in right_buttons) + gap * (len(right_buttons) - 1)
        x = max(self._header_width + margin, self.width() - margin - total_w)
        for btn in right_buttons:
            btn.move(x, y)
            btn.raise_()
            x += btn.width() + gap

    def _toggle_auto_scroll_button(self) -> None:
        self.set_auto_scroll(not self._auto_scroll)
        self.auto_scroll_changed.emit(self._auto_scroll)

    def _sync_auto_scroll_button(self) -> None:
        """Keep Auto Scroll chip + tooltip in sync with on/off state."""
        if not hasattr(self, "auto_scroll_button"):
            return
        on = self._auto_scroll
        self.auto_scroll_button.set_active(on)
        self.auto_scroll_button.setToolTip(
            "Auto Scroll ON — timeline follows the playhead (click to turn off)"
            if on
            else "Auto Scroll OFF — click to follow the playhead"
        )

    def _toggle_setup_mode(self) -> None:
        self._setup_mode = not self._setup_mode
        self.setup_button.set_active(self._setup_mode)
        self.update()

    def _toggle_box_select_mode(self) -> None:
        self._box_select_mode = not self._box_select_mode
        self.box_select_button.set_active(self._box_select_mode)
        self.update()

    def _build_video_track_overlay(self) -> None:
        """Video track header chrome: track Mute + an expand toggle that
        reveals, together (同步顯示), the per-selected-clip Video volume
        fader *and* a Music volume fader for Video/Music alignment balancing
        (real QSliders, styled like Master Volume — see theme.SLIDER_QSS)."""
        btn_size = QSize(22, 22)
        self.video_mute_button = IconButton(
            "speaker_mute",
            "Mute Video Track (silences every clip's own audio; picture keeps playing)",
            self,
            size=btn_size,
            overlay=True,
        )
        self.video_expand_button = IconButton(
            "chevron",
            "Show Video Clip Volume + Music Volume faders (for Video/Music balancing)",
            self,
            size=btn_size,
            overlay=True,
        )
        # Kept for older tests / API; the real toggle is video_show_button,
        # fixed on the Music header so show/hide stay in one place.
        self.video_hide_button = IconButton(
            "eye_off",
            "Hide Video + LTC Tracks (after alignment — Preview/Clean Output keep playing).",
            self,
            size=btn_size,
            overlay=True,
        )
        self.video_show_button = IconButton(
            "eye",
            "Show Video + LTC Tracks (LTC lane appears when a file stripe is known)",
            self,
            size=btn_size,
            overlay=True,
        )
        self.video_mute_button.clicked.connect(self._toggle_video_track_muted)
        self.video_expand_button.clicked.connect(self._toggle_video_track_expanded)
        self.video_hide_button.clicked.connect(self._hide_video_track_clicked)
        self.video_show_button.clicked.connect(self._toggle_video_track_from_eye)

        self.video_clip_volume_slider = QSlider(Qt.Orientation.Horizontal, self)
        self.video_clip_volume_slider.setRange(0, 100)
        self.video_clip_volume_slider.setValue(100)
        self.video_clip_volume_slider.setToolTip("Selected Video Clip volume")
        self.video_clip_volume_slider.setStyleSheet(SLIDER_QSS)
        self.video_clip_volume_slider.valueChanged.connect(self._on_video_clip_volume_slider)
        self.video_clip_volume_slider.hide()

        self.video_clip_volume_label = QLabel("100%", self)
        self.video_clip_volume_label.setStyleSheet("color: #a1a1aa; font-size: 11px; background: transparent;")
        self.video_clip_volume_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.video_clip_volume_label.hide()

        # Music-bed volume — shown alongside Video Clip volume whenever the
        # Video track chrome is expanded, so Music vs Video can be balanced
        # by eye/ear in one place instead of hunting for Master Volume.
        self.music_volume_caption = QLabel("Music", self)
        self.music_volume_caption.setStyleSheet("color: #71717a; font-size: 10px; background: transparent;")
        self.music_volume_caption.hide()

        self.music_volume_slider = QSlider(Qt.Orientation.Horizontal, self)
        self.music_volume_slider.setRange(0, 100)
        self.music_volume_slider.setValue(100)
        self.music_volume_slider.setToolTip(
            "Music bed volume for Video/Music balance (0–100%; independent of waveform gain)"
        )
        self.music_volume_slider.setStyleSheet(SLIDER_QSS)
        self.music_volume_slider.valueChanged.connect(self._on_music_volume_slider)
        self.music_volume_slider.hide()

        self.music_volume_label = QLabel("100%", self)
        self.music_volume_label.setStyleSheet("color: #a1a1aa; font-size: 11px; background: transparent;")
        self.music_volume_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.music_volume_label.hide()

        self.music_expand_button = IconButton(
            "chevron",
            "Show Music bed volume + waveform gain faders",
            self,
            size=btn_size,
            overlay=True,
        )
        self.music_expand_button.clicked.connect(self._toggle_music_header_expanded)

        self.audio_gain_caption = QLabel("Gain", self)
        self.audio_gain_caption.setStyleSheet("color: #71717a; font-size: 10px; background: transparent;")
        self.audio_gain_caption.hide()

        self.audio_gain_slider = QSlider(Qt.Orientation.Horizontal, self)
        self.audio_gain_slider.setRange(-120, 120)
        self.audio_gain_slider.setValue(0)
        self.audio_gain_slider.setToolTip("Music waveform gain (−12 to +12 dB; same as right-click volume line)")
        self.audio_gain_slider.setStyleSheet(SLIDER_QSS)
        self.audio_gain_slider.valueChanged.connect(self._on_audio_gain_slider)
        self.audio_gain_slider.hide()

        self.audio_gain_label = QLabel("0.0 dB", self)
        self.audio_gain_label.setStyleSheet("color: #a1a1aa; font-size: 11px; background: transparent;")
        self.audio_gain_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.audio_gain_label.hide()

        for w in (
            self.video_mute_button,
            self.video_expand_button,
            self.video_hide_button,
            self.video_show_button,
            self.music_expand_button,
        ):
            w.raise_()
        self._layout_video_track_overlay()
        self._layout_music_header_overlay()

    def _music_chrome_extra(self) -> float:
        return self._music_expand_extra if self._music_header_expanded else 0.0

    def _hide_video_track_clicked(self) -> None:
        self.set_show_video_track(False)

    def _show_video_track_clicked(self) -> None:
        self.set_show_video_track(True)

    def _toggle_video_track_from_eye(self) -> None:
        self.set_show_video_track(not self._show_video_track)

    def _sync_video_eye_button(self) -> None:
        """Eye stays on the Music header; icon flips between show / hide."""
        if not hasattr(self, "video_show_button"):
            return
        visible = self._video_lane_visible()
        if visible:
            self.video_show_button.set_kind("eye_off")
            self.video_show_button.setToolTip(
                "Hide Video + LTC Tracks (after alignment — Preview/Clean Output keep playing)"
            )
        else:
            self.video_show_button.set_kind("eye")
            self.video_show_button.setToolTip(
                "Show Video + LTC Tracks (LTC lane appears when a file stripe is known)"
            )
        self.video_show_button.set_active(visible)

    def _layout_music_header_overlay(self) -> None:
        if not hasattr(self, "music_expand_button"):
            return
        eye_header = self._video_eye_header_visible()
        self.music_expand_button.setVisible(eye_header)
        if eye_header:
            top = self._wave_bottom_y()
            btn_y = top - self.music_expand_button.height() - 2
            x = self._header_width - 6 - self.video_show_button.width()
            self.video_show_button.move(x, btn_y)
            self.video_show_button.raise_()
            x -= self.music_expand_button.width() + 3
            self.music_expand_button.move(x, btn_y)
            self.music_expand_button.raise_()
        if self._music_header_expanded:
            sub_y = self._wave_bottom_y() + 4
            label_w = 44
            slider_x = 8
            slider_w = max(40, self._header_width - 16 - label_w - 4)
            caption_y = sub_y + 2
            slider_y = caption_y + 12
            self.music_volume_caption.setGeometry(slider_x, caption_y, slider_w, 12)
            self.music_volume_slider.setGeometry(slider_x, slider_y, slider_w, 16)
            self.music_volume_label.setGeometry(
                slider_x + slider_w + 4, slider_y - 1, label_w, 18
            )
            caption_y2 = slider_y + 16 + 6
            slider_y2 = caption_y2 + 12
            self.audio_gain_caption.setGeometry(slider_x, caption_y2, slider_w, 12)
            self.audio_gain_slider.setGeometry(slider_x, slider_y2, slider_w, 16)
            self.audio_gain_label.setGeometry(
                slider_x + slider_w + 4, slider_y2 - 1, label_w, 18
            )
            for w in (
                self.music_volume_caption,
                self.music_volume_slider,
                self.music_volume_label,
                self.audio_gain_caption,
                self.audio_gain_slider,
                self.audio_gain_label,
            ):
                w.raise_()
                w.show()
        else:
            self.music_volume_caption.hide()
            self.music_volume_slider.hide()
            self.music_volume_label.hide()
            self.audio_gain_caption.hide()
            self.audio_gain_slider.hide()
            self.audio_gain_label.hide()

    def _layout_video_track_overlay(self) -> None:
        if not hasattr(self, "video_mute_button"):
            return
        visible = self._video_lane_visible()
        eye_header = self._video_eye_header_visible()
        self.video_mute_button.setVisible(visible)
        self.video_expand_button.setVisible(visible)
        # Hide/show lives on the fixed Music-header eye — not on Video Track.
        self.video_hide_button.setVisible(False)
        self.video_show_button.setVisible(eye_header)
        self._sync_video_eye_button()
        if not visible:
            self.video_clip_volume_slider.hide()
            self.video_clip_volume_label.hide()
            return
        top = self._video_lane_top_y()
        row_h = int(self._video_lane_base_height)
        btn_y = top + (row_h - self.video_mute_button.height()) // 2
        x = self._header_width - 6 - self.video_mute_button.width()
        self.video_mute_button.move(x, btn_y)
        x -= self.video_expand_button.width() + 3
        self.video_expand_button.move(x, btn_y)
        self.video_mute_button.raise_()
        self.video_expand_button.raise_()
        if self._video_track_expanded:
            sub_y = top + row_h
            label_w = 32
            slider_x = 8
            slider_w = max(40, self._header_width - 16 - label_w - 4)
            # Row 1: selected clip's Video volume (clip name caption is
            # painted separately in _paint_headers, just above this row).
            slider_y = sub_y + 20
            self.video_clip_volume_slider.setGeometry(slider_x, slider_y, slider_w, 16)
            self.video_clip_volume_label.setGeometry(
                slider_x + slider_w + 4, slider_y - 1, label_w, 18
            )
            self.video_clip_volume_slider.raise_()
            self.video_clip_volume_label.raise_()
            self.video_clip_volume_slider.show()
            self.video_clip_volume_label.show()
        else:
            self.video_clip_volume_slider.hide()
            self.video_clip_volume_label.hide()
        self._layout_music_header_overlay()

    def _toggle_video_track_muted(self) -> None:
        self.set_video_track_muted(not self._video_track_muted)
        self.video_track_mute_toggled.emit(self._video_track_muted)

    def set_video_track_muted(self, muted: bool) -> None:
        """Sync the Mute button visual state (call after loading a song)."""
        self._video_track_muted = bool(muted)
        if hasattr(self, "video_mute_button"):
            self.video_mute_button.set_active(self._video_track_muted)

    def _toggle_music_header_expanded(self) -> None:
        self._music_header_expanded = not self._music_header_expanded
        if hasattr(self, "music_expand_button"):
            self.music_expand_button.set_active(self._music_header_expanded)
        self._apply_layout_heights()
        self._layout_music_header_overlay()
        self._sync_music_volume_ui()
        self._sync_audio_gain_ui()
        self.update()

    def _toggle_video_track_expanded(self) -> None:
        self._video_track_expanded = not self._video_track_expanded
        if hasattr(self, "video_expand_button"):
            self.video_expand_button.set_active(self._video_track_expanded)
        self._apply_layout_heights()
        self._layout_video_track_overlay()
        self._sync_video_clip_volume_ui()
        self.update()

    def _sync_audio_gain_ui(self) -> None:
        if not hasattr(self, "audio_gain_slider"):
            return
        db = self._song.audio_gain_db if self._song is not None else 0.0
        tenths = int(round(self._clamp_gain_db(db) * 10))
        self.audio_gain_slider.blockSignals(True)
        self.audio_gain_slider.setValue(tenths)
        self.audio_gain_slider.blockSignals(False)
        self.audio_gain_label.setText(f"{self._clamp_gain_db(db):+.1f} dB")

    def _on_audio_gain_slider(self, value: int) -> None:
        if self._song is None:
            return
        db = self._clamp_gain_db(value / 10.0)
        self.audio_gain_label.setText(f"{db:+.1f} dB")
        if abs(db - self._song.audio_gain_db) < 1e-4:
            return
        self._song.audio_gain_db = db
        self.audio_gain_changed.emit(db)
        self._invalidate_scrub_backdrop()
        self.update()

    def _sync_video_clip_volume_ui(self) -> None:
        if not hasattr(self, "video_clip_volume_slider"):
            return
        clip = self._single_selected_video_clip()
        pct = int(round(clip.volume * 100)) if clip is not None else 100
        self.video_clip_volume_slider.blockSignals(True)
        self.video_clip_volume_slider.setValue(pct)
        self.video_clip_volume_slider.blockSignals(False)
        self.video_clip_volume_slider.setEnabled(clip is not None)
        self.video_clip_volume_label.setText(f"{pct}%" if clip is not None else "—")
        tip = f"Video Clip Volume — {clip.name}" if clip is not None else "Select a Video Clip to adjust its volume"
        self.video_clip_volume_slider.setToolTip(tip)

    def _on_video_clip_volume_slider(self, value: int) -> None:
        clip = self._single_selected_video_clip()
        if clip is None:
            return
        clip.volume = max(0.0, min(1.0, value / 100.0))
        self.video_clip_volume_label.setText(f"{int(value)}%")
        self.video_clip_volume_changed.emit(clip.id, clip.volume)
        self.update()

    def _sync_music_volume_ui(self) -> None:
        if not hasattr(self, "music_volume_slider"):
            return
        volume = self._song.music_volume if self._song is not None else 1.0
        pct = int(round(max(0.0, min(1.0, volume)) * 100))
        self.music_volume_slider.blockSignals(True)
        self.music_volume_slider.setValue(pct)
        self.music_volume_slider.blockSignals(False)
        self.music_volume_label.setText(f"{pct}%")

    def _on_music_volume_slider(self, value: int) -> None:
        if self._song is None:
            return
        volume = max(0.0, min(1.0, value / 100.0))
        self._song.music_volume = volume
        self.music_volume_label.setText(f"{int(value)}%")
        self.music_volume_changed.emit(volume)

    def _on_video_waveform_ready(self) -> None:
        """Called from the waveform worker thread — must not touch Qt widgets."""
        self._video_waveforms_ready.emit()

    def _apply_video_waveform_ready(self) -> None:
        """GUI-thread slot: refresh static backdrop once peaks land."""
        if self._playing:
            # Avoid rebuilding the wide play-cache mid-playback (heavy + races
            # with background PyAV work on the same clip file).
            self._video_waveform_pending_refresh = True
            return
        self._video_waveform_pending_refresh = False
        self._invalidate_scrub_backdrop()
        self.update()

    def set_song(self, song: Song | None) -> None:
        self._song = song
        self._selected_mark_ids.clear()
        self._selected_clip_ids.clear()
        self._dragging_audio_gain = False
        self._audio_gain_zone = None
        self._audio_gain_drag_bounds = None
        self.set_video_track_muted(song.video_track_muted if song is not None else False)
        # Wave/LTC gain line visibility is project-global — do not reset per song.
        if song is not None:
            song.show_video_track = self._show_video_track
            song.show_ltc_track = self._show_video_track
            self._ltc_lane_height = max(
                self._ltc_lane_min_height, min(400.0, float(song.ltc_lane_height))
            )
        self._sync_video_clip_volume_ui()
        self._sync_music_volume_ui()
        self._sync_audio_gain_ui()
        if song is not None:
            self._show_mark_tracks = song.show_mark_tracks
            self._show_mark_stem = song.show_mark_stem
            self._video_lane_base_height = self._clamp_video_lane_height(song.video_lane_height)
            self._lane_height = self._clamp_mark_lane_height(self._project_mark_lane_height)
            # Mark line style/width come from project (apply_mark_line_settings).
        self._video_waveform_cache.clear()
        self._video_waveform_pending_refresh = False
        self._invalidate_scrub_backdrop()
        if song is not None and song.video_clips:
            clips = list(song.video_clips)

            def _preload_video_waveforms() -> None:
                if self._song is song:
                    self._video_waveform_cache.preload(clips)
                    self._invalidate_scrub_backdrop()
                    self.update()

            QTimer.singleShot(0, _preload_video_waveforms)
        self._apply_layout_heights()
        self._layout_video_track_overlay()
        self.update()

    def refresh_video_clip_waveforms(self) -> None:
        """Re-request peaks after clip trim/move (cache keys include clip params)."""
        if self._song is None:
            return
        self._video_waveform_cache.preload(list(self._song.video_clips))
        self._invalidate_scrub_backdrop()
        self.update()

    def apply_mark_line_settings(
        self,
        *,
        style: str,
        width: float,
        dash_on: float,
        dash_off: float,
        waveform_color: str | None = None,
        playhead_color: str | None = None,
    ) -> None:
        """Project-global mark line look + waveform / playhead colors."""
        if style not in ("solid", "dash", "dot"):
            style = "solid"
        self._mark_line_style = style  # type: ignore[assignment]
        self._mark_line_width = max(1.0, min(12.0, float(width)))
        self._mark_dash_on = max(1.0, min(40.0, float(dash_on)))
        self._mark_dash_off = max(1.0, min(40.0, float(dash_off)))
        if waveform_color is not None:
            q = QColor(waveform_color)
            self._waveform_color = q.name() if q.isValid() else "#3dd68c"
        if playhead_color is not None:
            q = QColor(playhead_color)
            self._playhead_color = q.name() if q.isValid() else "#ff5a5f"
        self.update()

    def apply_mark_lane_height(self, height: float) -> None:
        """Project-global mark lane row height (pixels)."""
        clamped = self._clamp_mark_lane_height(height)
        self._project_mark_lane_height = float(clamped)
        if clamped == self._lane_height:
            return
        self._lane_height = clamped
        self._apply_layout_heights()
        self.update()

    def apply_mark_track_colors(self, show: bool) -> None:
        """Project-global tint on all mark-track rows."""
        show = bool(show)
        if show == self._show_mark_track_colors:
            return
        self._show_mark_track_colors = show
        self._apply_layout_heights()
        self._invalidate_scrub_backdrop()
        self.update()

    def selected_mark_ids(self) -> list[str]:
        return list(self._selected_mark_ids)

    def set_selected_mark_ids(self, mark_ids: set[str] | list[str], *, emit: bool = True) -> None:
        new_ids = set(mark_ids)
        if new_ids == self._selected_mark_ids:
            return
        self._selected_mark_ids = new_ids
        if new_ids and self._selected_clip_ids:
            self._selected_clip_ids = set()
        self.update()
        if emit:
            self.selection_changed.emit(list(self._selected_mark_ids))

    def clear_selection(self, *, emit: bool = True) -> None:
        self.set_selected_mark_ids([], emit=emit)
        self.set_selected_video_clip_ids([], emit=emit)

    def selected_video_clip_ids(self) -> list[str]:
        return list(self._selected_clip_ids)

    def set_selected_video_clip_ids(self, clip_ids: set[str] | list[str], *, emit: bool = True) -> None:
        new_ids = set(clip_ids)
        if new_ids == self._selected_clip_ids:
            return
        self._selected_clip_ids = new_ids
        if new_ids and self._selected_mark_ids:
            self._selected_mark_ids = set()
        self._sync_video_clip_volume_ui()
        self.update()
        if emit:
            self.video_clip_selection_changed.emit(list(self._selected_clip_ids))

    def _video_lane_visible(self) -> bool:
        return self._song is not None and self._show_video_track

    def _video_eye_header_visible(self) -> bool:
        """Eye toggle stays on the Music header (same spot whether lanes are open)."""
        return self._song is not None

    def _ltc_available(self) -> bool:
        return self._ltc_channel is not None and self._ltc_audio is not None

    def _ltc_lane_visible(self) -> bool:
        """LTC inspect lane shares the Video eye — shown only when Video is shown."""
        return self._ltc_available() and self._video_lane_visible()

    def set_show_video_track(self, visible: bool, *, emit: bool = True) -> None:
        """Show / hide Video + LTC lanes together (Preview / Clean Output keep playing)."""
        visible = bool(visible)
        changed = visible != self._show_video_track or (
            self._song is not None and self._song.show_video_track != visible
        )
        self._show_video_track = visible
        if self._song is not None:
            self._song.show_video_track = visible
            self._song.show_ltc_track = visible
        if not visible:
            self._video_track_expanded = False
            if hasattr(self, "video_expand_button"):
                self.video_expand_button.set_active(False)
            self.set_selected_video_clip_ids([], emit=False)
        self._apply_layout_heights()
        self._layout_video_track_overlay()
        self.update()
        if emit and changed:
            self.video_track_visibility_changed.emit(visible)
            self.ltc_track_visibility_changed.emit(visible)

    def set_show_ltc_track(self, visible: bool, *, emit: bool = True) -> None:
        """Alias — LTC is bound to the Video eye."""
        self.set_show_video_track(visible, emit=emit)

    def set_show_wave_gain_line(self, visible: bool, *, emit: bool = True) -> None:
        visible = bool(visible)
        if visible == self._show_wave_gain_line:
            return
        self._show_wave_gain_line = visible
        self.update()
        if emit:
            self.wave_gain_line_visibility_changed.emit(visible)

    def set_show_ltc_gain_line(self, visible: bool, *, emit: bool = True) -> None:
        visible = bool(visible)
        if visible == self._show_ltc_gain_line:
            return
        self._show_ltc_gain_line = visible
        self.update()
        if emit:
            self.ltc_gain_line_visibility_changed.emit(visible)

    def set_ltc_audio(
        self,
        audio: AudioBuffer | None,
        *,
        channel: int | None = None,
    ) -> None:
        """Feed the LTC inspect lane (one file channel). ``None`` clears it."""
        self._ltc_audio = audio
        self._ltc_channel = int(channel) if channel is not None and audio is not None else None
        self._apply_layout_heights()
        self._layout_video_track_overlay()
        self.update()

    @property
    def _video_lane_height(self) -> float:
        """Total video lane height, including the expanded clip-volume row."""
        extra = self._video_expand_extra if self._video_track_expanded else 0.0
        return self._video_lane_base_height + extra

    def _mark_lane_gap_px(self) -> int:
        """Black spacers between tinted mark rows (track colors on only)."""
        return 2 if self._show_mark_track_colors else 0

    def _marks_content_height(self) -> int:
        n = self._visible_lane_count()
        if n <= 0:
            return 0
        gap = self._mark_lane_gap_px()
        return n * self._lane_height + max(0, n - 1) * gap

    def _marks_band_height(self) -> int:
        if not self._show_mark_tracks:
            return 0
        h = self._marks_content_height()
        if h > 0 and self._show_mark_lane_resize_bar:
            h += self._mark_lane_split_h
        return h

    def _mark_lane_split_y(self) -> int:
        return self._tracks_top_y() + self._marks_content_height()

    def _near_mark_lane_split(self, y: float) -> bool:
        if (
            not self._show_mark_lane_resize_bar
            or not self._show_mark_tracks
            or self._visible_lane_count() == 0
        ):
            return False
        return abs(y - self._mark_lane_split_y()) <= self._mark_lane_split_hit

    def _clamp_mark_lane_height(self, height: float) -> int:
        return int(max(24, min(80, round(float(height)))))

    def set_mark_lane_height(self, height: float) -> None:
        clamped = self._clamp_mark_lane_height(height)
        if clamped == self._lane_height:
            return
        self._lane_height = clamped
        self._project_mark_lane_height = float(clamped)
        self._apply_layout_heights()
        self.update()
        self.mark_lane_height_changed.emit(float(clamped))

    @staticmethod
    def _clamp_gain_db(db: float) -> float:
        return float(max(-12.0, min(12.0, db)))

    @staticmethod
    def _volume_to_gain_db(volume: float) -> float:
        return TimelineWidget._clamp_gain_db(20.0 * math.log10(max(float(volume), 1e-6)))

    @staticmethod
    def _gain_db_to_volume(db: float) -> float:
        return float(min(1.0, max(0.0, 10.0 ** (TimelineWidget._clamp_gain_db(db) / 20.0))))

    def _gain_travel_bounds(self, top: float, bottom: float) -> tuple[float, float]:
        """Inset vertical travel so +12/-12 dB stops short of the track edges."""
        span = max(1.0, bottom - top)
        inset = span * (1.0 - self._audio_gain_travel_span) * 0.5
        return top + inset, bottom - inset

    def _wave_gain_bounds(self) -> tuple[float, float] | None:
        if self._audio is None and not self._audio_loading:
            return None
        top = float(self._ruler_height)
        bottom = float(self._wave_bottom_y() - self._wave_split_hit)
        if bottom <= top:
            return None
        return top, bottom

    def _wave_gain_travel_bounds(self) -> tuple[float, float] | None:
        bounds = self._wave_gain_bounds()
        if bounds is None:
            return None
        return self._gain_travel_bounds(*bounds)

    def _ltc_gain_bounds(self) -> tuple[float, float] | None:
        if not self._ltc_lane_visible() or self._ltc_audio is None:
            return None
        top = float(self._ltc_lane_top_y())
        bottom = top + float(self._ltc_band_height())
        return top, bottom

    def _ltc_gain_travel_bounds(self) -> tuple[float, float] | None:
        bounds = self._ltc_gain_bounds()
        if bounds is None:
            return None
        return self._gain_travel_bounds(*bounds)

    def _y_for_gain_db(self, db: float, top: float, bottom: float) -> float:
        frac = (12.0 - self._clamp_gain_db(db)) / 24.0
        return top + frac * max(1.0, bottom - top)

    def _gain_db_for_y(self, y: float, top: float, bottom: float) -> float:
        frac = (y - top) / max(1.0, bottom - top)
        return self._clamp_gain_db(12.0 - frac * 24.0)

    def _current_wave_gain_db(self) -> float:
        if self._song is None:
            return 0.0
        return self._clamp_gain_db(float(self._song.audio_gain_db))

    def _current_ltc_music_gain_db(self) -> float:
        volume = self._song.music_volume if self._song is not None else 1.0
        return self._volume_to_gain_db(volume)

    def _near_audio_gain_line(self, x: float, y: float) -> str | None:
        if x < self._header_width:
            return None
        hit = self._audio_gain_hit_px
        if self._show_wave_gain_line:
            bounds = self._wave_gain_travel_bounds()
            if bounds is not None:
                top, bottom = bounds
                line_y = self._y_for_gain_db(self._current_wave_gain_db(), top, bottom)
                if abs(y - line_y) <= hit:
                    return "wave"
        if self._show_ltc_gain_line:
            bounds = self._ltc_gain_travel_bounds()
            if bounds is not None:
                top, bottom = bounds
                line_y = self._y_for_gain_db(self._current_ltc_music_gain_db(), top, bottom)
                if abs(y - line_y) <= hit:
                    return "ltc"
        return None

    def _apply_gain_at_y(self, y: float, zone: str) -> None:
        if self._song is None:
            return
        if zone == "wave":
            bounds = self._audio_gain_drag_bounds or self._wave_gain_travel_bounds()
            if bounds is None:
                return
            top, bottom = bounds
            db = self._gain_db_for_y(y, top, bottom)
            if abs(db - self._song.audio_gain_db) < 1e-4:
                return
            self._song.audio_gain_db = db
            self.audio_gain_changed.emit(db)
            self._sync_audio_gain_ui()
        elif zone == "ltc":
            bounds = self._audio_gain_drag_bounds or self._ltc_gain_travel_bounds()
            if bounds is None:
                return
            top, bottom = bounds
            db = self._gain_db_for_y(y, top, bottom)
            volume = self._gain_db_to_volume(db)
            if abs(volume - self._song.music_volume) < 1e-4:
                return
            self._song.music_volume = volume
            self._sync_music_volume_ui()
            self.music_volume_changed.emit(volume)
        self._invalidate_scrub_backdrop()
        self.update()

    def _paint_mark_lane_splitter(self, painter: QPainter) -> None:
        if (
            not self._show_mark_lane_resize_bar
            or not self._show_mark_tracks
            or self._visible_lane_count() == 0
        ):
            return
        bottom = self._mark_lane_split_y()
        active = self._resizing_mark_lanes or self._mark_lane_split_hover
        color = QColor("#5a5a5a") if active else QColor("#0d0d0d")
        right = self._paint_right()
        painter.fillRect(0, bottom - 2, right, 4, color)
        if active:
            mid_x = self._header_width + (right - self._header_width) // 2
            painter.setPen(QPen(QColor("#a0a0a0"), 1))
            painter.drawLine(mid_x - 18, bottom, mid_x + 18, bottom)

    def _paint_audio_gain_overlays(self, painter: QPainter) -> None:
        right = self._paint_right()
        if self._show_wave_gain_line:
            bounds = self._wave_gain_travel_bounds()
            if bounds is not None:
                self._paint_gain_line(
                    painter,
                    bounds,
                    self._current_wave_gain_db(),
                    QColor("#f4f4f5"),
                    right,
                    hovered=self._audio_gain_line_active("wave"),
                )
        if self._show_ltc_gain_line:
            bounds = self._ltc_gain_travel_bounds()
            if bounds is not None:
                self._paint_gain_line(
                    painter,
                    bounds,
                    self._current_ltc_music_gain_db(),
                    QColor("#fbbf24"),
                    right,
                    label_prefix="Music ",
                    hovered=self._audio_gain_line_active("ltc"),
                )

    def _audio_gain_line_active(self, zone: str) -> bool:
        if self._dragging_audio_gain and self._audio_gain_zone == zone:
            return True
        return self._hover_audio_gain_zone == zone

    def _paint_gain_line(
        self,
        painter: QPainter,
        bounds: tuple[float, float],
        db: float,
        color: QColor,
        right: int,
        *,
        label_prefix: str = "",
        hovered: bool = False,
    ) -> None:
        top, bottom = bounds
        line_y = self._y_for_gain_db(db, top, bottom)
        line_left = float(self._header_width)
        line_right = float(right)
        line_w = max(1.0, line_right - line_left)

        if hovered:
            glow = QColor(color)
            glow.setAlpha(56)
            painter.fillRect(QRectF(line_left, line_y - 5.0, line_w, 10.0), glow)
            line_color = QColor(color).lighter(135)
            pen_w = 3
            cap_r = 3.5
            painter.setBrush(line_color)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(QPointF(line_left, line_y), cap_r, cap_r)
            painter.drawEllipse(QPointF(line_right, line_y), cap_r, cap_r)
        else:
            line_color = color
            pen_w = 2

        painter.setPen(QPen(line_color, pen_w))
        painter.drawLine(QPointF(line_left, line_y), QPointF(line_right, line_y))
        painter.setPen(line_color)
        text = f"{label_prefix}{db:+.1f} dB"
        painter.drawText(int(line_left) + 8, int(line_y) - 4, text)

    def _video_lane_top_y(self) -> int:
        """Video sits directly under the Music waveform (+ optional Music chrome)."""
        return self._wave_bottom_y() + int(self._music_chrome_extra())

    def _ltc_band_height(self) -> int:
        return int(self._ltc_lane_height) if self._ltc_lane_visible() else 0

    def _ltc_lane_top_y(self) -> int:
        """LTC sits under Video (Music → Video → LTC → Marks)."""
        y = self._video_lane_top_y()
        if self._video_lane_visible():
            return y + int(self._video_lane_height)
        return y

    def _tracks_top_y(self) -> int:
        """Y where mark lanes begin — below waveform + optional Video + LTC."""
        return self._ltc_lane_top_y() + self._ltc_band_height()

    def _tracks_bottom_y(self) -> int:
        return self._tracks_top_y() + self._marks_band_height()

    def _video_lane_clip_bottom_y(self) -> int:
        return self._video_lane_top_y() + int(self._video_lane_base_height)

    def _near_video_lane_split(self, y: float) -> bool:
        if not self._video_lane_visible():
            return False
        return abs(y - self._video_lane_clip_bottom_y()) <= self._video_lane_split_hit

    def set_video_lane_height(self, height: float) -> None:
        """Grow / shrink the Video clip row (waveforms)."""
        clamped = self._clamp_video_lane_height(height)
        if clamped == self._video_lane_base_height:
            return
        self._video_lane_base_height = clamped
        if self._song is not None:
            self._song.video_lane_height = clamped
        self._apply_layout_heights()
        self._layout_video_track_overlay()
        self.update()

    def _max_video_lane_height(self) -> float:
        return max(self._video_lane_min_height, 2400.0)

    def _clamp_video_lane_height(self, height: float) -> float:
        return max(self._video_lane_min_height, min(self._max_video_lane_height(), float(height)))

    def _in_video_lane(self, x: float, y: float) -> bool:
        """Clip drag/drop/select area — always the base row, even when expanded
        (the extra row below is chrome for the per-clip volume fader)."""
        if not self._video_lane_visible() or x < self._header_width:
            return False
        top = self._video_lane_top_y()
        return top <= y < top + self._video_lane_base_height

    def _single_selected_video_clip(self) -> VideoClip | None:
        if self._song is None or len(self._selected_clip_ids) != 1:
            return None
        return self._song.video_clip_by_id(next(iter(self._selected_clip_ids)))

    def _hit_video_clip(
        self,
        x: float,
        y: float,
        *,
        allow_locked_edit: bool = False,
    ) -> tuple[str, str] | None:
        """Return (clip_id, zone) with zone in {'left', 'right', 'body'}; topmost-drawn wins.

        Locked clips normally only hit as ``body`` (selection). Hold Shift
        (``allow_locked_edit``) to also hit trim edges and allow move/trim.
        """
        if self._song is None or not self._in_video_lane(x, y):
            return None
        for clip in reversed(self._song.video_clips):
            x0 = self._x_for_time(clip.start_seconds)
            x1 = self._x_for_time(clip.end_seconds)
            if x1 < x0:
                x0, x1 = x1, x0
            if x0 - self._clip_edge_hit <= x <= x1 + self._clip_edge_hit:
                can_edit = (not clip.locked) or allow_locked_edit
                if can_edit and abs(x - x0) <= self._clip_edge_hit:
                    return (clip.id, "left")
                if can_edit and abs(x - x1) <= self._clip_edge_hit:
                    return (clip.id, "right")
                if x0 <= x <= x1:
                    return (clip.id, "body")
        return None

    def _in_mark_tracks(self, x: float, y: float) -> bool:
        """Mark lane rows below Video/LTC (box-select zone)."""
        if not self._show_mark_tracks or self._song is None:
            return False
        if x < self._header_width:
            return False
        top = self._tracks_top_y()
        bottom = self._mark_lane_split_y() if self._visible_lane_count() > 0 else self._tracks_bottom_y()
        return top <= y < bottom

    def _lane_rects(self) -> list[tuple[int, float, float]]:
        """Return (lane_index, y0, y1) for visible lanes."""
        if self._song is None or not self._show_mark_tracks:
            return []
        out: list[tuple[int, float, float]] = []
        y = float(self._tracks_top_y())
        visible = [lane for lane in self._song.mark_lanes if lane.visible]
        for i, lane in enumerate(visible):
            out.append((lane.index, y, y + self._lane_height))
            y += self._lane_height
            if i < len(visible) - 1:
                y += self._mark_lane_gap_px()
        return out

    def _lane_index_at(self, x: float, y: float) -> int | None:
        """Mark lane under the cursor (header or lane body), visible lanes only."""
        if self._song is None or not self._show_mark_tracks:
            return None
        for lane_index, y0, y1 in self._lane_rects():
            if y0 <= y < y1 and (
                x < self._header_width or self._in_mark_tracks(x, y)
            ):
                return lane_index
        return None

    @staticmethod
    def _lane_accent_color(lane) -> QColor:  # noqa: ANN001
        color = QColor(lane.color or "#4C8BF5")
        return color if color.isValid() else QColor("#4C8BF5")

    def _lane_row_fill(self, lane, *, header: bool = False) -> QColor:  # noqa: ANN001
        color = self._lane_accent_color(lane)
        alpha = 44 if header else (36 if lane.cue_id_enabled else 28)
        fill = QColor(color)
        fill.setAlpha(alpha)
        return fill

    def _paint_mark_lane_header_label(
        self,
        painter: QPainter,
        lane,
        *,
        y: int,
        text_w: int,
        fm,
    ) -> None:  # noqa: ANN001
        """Colored shortcut + name on neutral header — no row tint."""
        accent = self._lane_accent_color(lane)
        shortcut = (lane.shortcut or str(lane.index)).strip()
        name = (lane.name or "").strip()
        row_h = int(self._lane_height)
        gap = "  "
        shortcut_w = fm.horizontalAdvance(shortcut + gap) if shortcut else 0
        name_w = max(0, text_w - shortcut_w)
        elided_name = fm.elidedText(name, Qt.TextElideMode.ElideRight, name_w) if name else ""
        base_font = painter.font()
        bold = QFont(base_font)
        bold.setWeight(QFont.Weight.Bold)
        if shortcut:
            painter.setFont(bold)
            painter.setPen(accent)
            painter.drawText(
                QRect(8, y, min(text_w, shortcut_w), row_h),
                int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                shortcut,
            )
        painter.setFont(base_font)
        painter.setPen(accent)
        painter.drawText(
            QRect(8 + shortcut_w, y, name_w, row_h),
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
            elided_name,
        )
        painter.setFont(base_font)

    def _hit_mark_lane_header(self, x: float, y: float) -> int | None:
        """Return lane index when clicking the left name header of a Mark track."""
        if x >= self._header_width or self._song is None or not self._show_mark_tracks:
            return None
        for lane_index, y0, y1 in self._lane_rects():
            if y0 <= y < y1:
                return lane_index
        return None

    def _rename_mark_lane_at(self, lane_index: int) -> None:
        if self._song is None:
            return
        lane = self._song.lane_by_index(lane_index)
        if lane is None:
            return
        text, ok = QInputDialog.getText(
            self,
            "Rename Mark",
            f"Name for Mark track {lane.shortcut or lane.index}:",
            text=lane.name,
        )
        if not ok:
            return
        new_name = text.strip()
        if not new_name or new_name == lane.name:
            return
        lane.name = new_name
        self.lane_name_changed.emit(lane_index, new_name)
        self.update()

    def _marks_in_box(self, rect: QRectF) -> set[str]:
        if self._song is None:
            return set()
        hit: set[str] = set()
        lane_rects = {idx: (y0, y1) for idx, y0, y1 in self._lane_rects()}
        wave_top = float(self._ruler_height)
        wave_bottom = float(self._wave_bottom_y())
        for mark in self._song.marks:
            lane = self._song.lane_by_index(mark.lane_index)
            if lane is not None and not lane.visible:
                continue
            x = self._x_for_time(mark.time_seconds)
            if x < self._header_width - 2 or x > self.width() + 2:
                continue
            lane_pair = lane_rects.get(mark.lane_index)
            if lane_pair is not None:
                y0, y1 = lane_pair
                mark_rect = QRectF(x - 6, y0 + 2, 12, max(4.0, y1 - y0 - 4))
                if rect.intersects(mark_rect):
                    hit.add(mark.id)
                    continue
            # Waveform overlay: time-range select while reading the wave.
            if rect.bottom() > wave_top and rect.top() < wave_bottom:
                if rect.left() <= x <= rect.right():
                    hit.add(mark.id)
        return hit

    def _selection_box_rect(self) -> QRectF:
        return QRectF(self._box_origin, self._box_current).normalized()

    def _emit_box_preview(self) -> None:
        boxed = self._marks_in_box(self._selection_box_rect())
        if self._box_additive:
            self._selected_mark_ids = set(self._box_base_ids) | boxed
        else:
            self._selected_mark_ids = boxed
        self.update()

    def event(self, e) -> bool:  # noqa: ANN001, N802
        if e.type() == QEvent.Type.ShortcutOverride:
            key = e.key()
            if key in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
                if self._selected_mark_ids or self._selected_clip_ids:
                    e.accept()
        return super().event(e)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            if self._selected_clip_ids:
                self.delete_video_clips_requested.emit(list(self._selected_clip_ids))
                event.accept()
                return
            if self._selected_mark_ids:
                self.delete_requested.emit(list(self._selected_mark_ids))
                event.accept()
                return
        if event.key() == Qt.Key.Key_A and event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            if self._song is not None:
                self.set_selected_mark_ids([m.id for m in self._song.marks])
                event.accept()
                return
        if event.key() == Qt.Key.Key_Escape:
            self.clear_selection()
            event.accept()
            return
        super().keyPressEvent(event)

    def set_show_mark_tracks(self, visible: bool) -> None:
        self._show_mark_tracks = visible
        if self._song is not None:
            self._song.show_mark_tracks = visible
        self._apply_layout_heights()
        self.update()

    def set_mark_line_style(self, style: str) -> None:
        if style not in ("solid", "dash", "dot"):
            style = "solid"
        self._mark_line_style = style  # type: ignore[assignment]
        self.update()

    def set_mark_dash_spacing(self, spacing: float) -> None:
        spacing = max(1.0, min(40.0, float(spacing)))
        self._mark_dash_on = spacing
        self._mark_dash_off = spacing
        self.update()

    def set_mark_line_width(self, width: float) -> None:
        self._mark_line_width = max(1.0, min(12.0, float(width)))
        self.update()

    def set_loop_region(
        self,
        a: float | None,
        b: float | None,
        *,
        enabled: bool = False,
    ) -> None:
        self._loop_a = a
        self._loop_b = b
        self._loop_enabled = enabled
        # Loop markers are painted live on top of the play/scrub backdrop;
        # still invalidate so a full rebuild picks them up when needed.
        self._invalidate_scrub_backdrop()
        self.update()

    def apply_song_display_settings(self) -> None:
        """Reload per-song display fields after Display dialog edits."""
        if self._song is None:
            return
        self._show_mark_tracks = self._song.show_mark_tracks
        self._show_mark_stem = self._song.show_mark_stem
        self.set_show_video_track(self._song.show_video_track, emit=False)
        self._ltc_lane_height = max(
            self._ltc_lane_min_height, min(400.0, float(self._song.ltc_lane_height))
        )
        self._apply_layout_heights()
        self._layout_video_track_overlay()
        self.update()

    def _visible_lane_count(self) -> int:
        if not self._show_mark_tracks:
            return 0
        if self._song is None:
            return 9
        return sum(1 for lane in self._song.mark_lanes if lane.visible)
    def set_audio(self, audio: AudioBuffer | None, *, reset_view: bool = True) -> None:
        self._audio = audio
        if audio is not None:
            self._audio_loading = False
            self._audio_loading_label = ""
            if reset_view:
                # Start moderately zoomed for beat work; user can zoom further.
                self._pixels_per_second = 150.0
                self._scroll_x = 0.0
            else:
                # Keep the user's current zoom when switching songs; only
                # clamp so a shorter song still fits the view minimum.
                self._pixels_per_second = max(
                    self._min_pixels_per_second(), float(self._pixels_per_second)
                )
                self._clamp_scroll()
        self._invalidate_scrub_backdrop()
        self.update()

    def pixels_per_second(self) -> float:
        return float(self._pixels_per_second)

    def set_audio_loading(self, loading: bool, label: str = "") -> None:
        """Show a waveform-pane placeholder while audio decodes off the UI thread."""
        self._audio_loading = bool(loading)
        self._audio_loading_label = (label or "").strip()
        if loading:
            self._audio = None
            self._ltc_audio = None
            self._ltc_channel = None
            self._layout_video_track_overlay()
        self.update()

    def set_auto_scroll(self, enabled: bool) -> None:
        self._auto_scroll = bool(enabled)
        self._sync_auto_scroll_button()
        if self._auto_scroll:
            self._view_pinned = False
            self._follow_playhead()
        self.update()

    def auto_scroll(self) -> bool:
        return self._auto_scroll

    def set_playing(self, playing: bool) -> None:
        was = self._playing
        self._playing = bool(playing)
        # Resume follow on play so a prior click/scrub/pan doesn't leave the
        # view stuck until the user zooms with the mouse wheel.
        if self._playing and not was and self._auto_scroll and not self._scrubbing:
            self._view_pinned = False
            self._center_on_playhead()
            self._invalidate_scrub_backdrop()
        if was != self._playing:
            # Play uses the same static-backdrop path as scrub; rebuild once.
            self._invalidate_scrub_backdrop()
            self._update_video_lane()
            if not self._playing and self._video_waveform_pending_refresh:
                self._video_waveform_pending_refresh = False
                self._invalidate_scrub_backdrop()
            self.update()

    def _begin_box_select(
        self,
        pos: QPointF,
        *,
        additive: bool,
        click_seek: float | None = None,
    ) -> None:
        self._box_selecting = True
        self._box_additive = additive
        self._box_base_ids = set(self._selected_mark_ids) if additive else set()
        self._box_origin = pos
        self._box_current = pos
        self._box_click_seek = click_seek
        self.grabMouse()
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setFocus(Qt.FocusReason.MouseFocusReason)
        if not additive:
            self._selected_mark_ids.clear()
        self.update()

    def _begin_pan(self, x: float, *, click_seek: float | None = None) -> None:
        self._panning = True
        self._pan_moved = False
        self._pan_click_seek = click_seek
        self._pan_origin_x = x
        self._pan_origin_scroll = self._scroll_x
        self._view_pinned = True
        self.grabMouse()
        self.setCursor(Qt.CursorShape.ClosedHandCursor)
        self.setFocus(Qt.FocusReason.MouseFocusReason)

    def _cursor_for_mark_hover(self, x: float, y: float) -> Qt.CursorShape:
        if not self._setup_mode:
            return Qt.CursorShape.PointingHandCursor
        if self._in_mark_tracks(x, y):
            return Qt.CursorShape.SizeHorCursor
        return Qt.CursorShape.ArrowCursor

    def _cursor_for_loop_hover(self, x: float, y: float) -> Qt.CursorShape:
        if self._in_waveform(x, y):
            return Qt.CursorShape.ArrowCursor
        return Qt.CursorShape.SizeHorCursor

    def _restore_hover_cursor(self, x: float, y: float) -> None:
        from PySide6.QtWidgets import QApplication

        shift = bool(
            QApplication.keyboardModifiers() & Qt.KeyboardModifier.ShiftModifier
        )
        clip_hit = self._hit_video_clip(x, y, allow_locked_edit=shift)
        if self._near_wave_split(y):
            self.setCursor(Qt.CursorShape.SizeVerCursor)
        elif self._near_video_lane_split(y):
            self.setCursor(Qt.CursorShape.SizeVerCursor)
        elif self._near_mark_lane_split(y):
            self.setCursor(Qt.CursorShape.SizeVerCursor)
        elif (gain_zone := self._near_audio_gain_line(x, y)) is not None:
            self.setCursor(Qt.CursorShape.SizeVerCursor)
            del gain_zone
        elif self._hit_mark_lane_header(x, y) is not None:
            self.setCursor(Qt.CursorShape.PointingHandCursor)
        elif self._hit_loop_handle(x, y) is not None:
            self.setCursor(self._cursor_for_loop_hover(x, y))
        elif self._hit_mark_at(x, y) is not None:
            self.setCursor(self._cursor_for_mark_hover(x, y))
        elif clip_hit is not None:
            self.setCursor(
                Qt.CursorShape.SizeHorCursor
                if clip_hit[1] in ("left", "right")
                else Qt.CursorShape.OpenHandCursor
            )
        elif self._box_select_mode and self._in_mark_tracks(x, y):
            self.setCursor(Qt.CursorShape.CrossCursor)
        elif self._in_scrub_zone(x, y):
            self.setCursor(Qt.CursorShape.ArrowCursor)
        else:
            self.setCursor(Qt.CursorShape.ArrowCursor)

    def _hit_loop_handle(self, x: float, y: float) -> str | None:
        """Return 'a' / 'b' when cursor is near a loop marker line."""
        del y
        if self._song is None or x < self._header_width:
            return None
        best: str | None = None
        best_dist = 9.0
        for name, t in (("a", self._loop_a), ("b", self._loop_b)):
            if t is None:
                continue
            dist = abs(self._x_for_time(t) - x)
            if dist <= best_dist:
                best_dist = dist
                best = name
        return best

    def _set_loop_handle_time(self, which: str, seconds: float) -> None:
        t = min(max(0.0, float(seconds)), self._duration())
        if which == "a":
            self._loop_a = t
        elif which == "b":
            self._loop_b = t
        self.loop_changed.emit(self._loop_a, self._loop_b)
        self.update()

    def playhead_seconds(self) -> float:
        """Visual playhead time — authoritative while scrubbing mid-drag.

        Mid-scrub updates ``_position`` locally; the audio engine only seeks on
        press/release. Mark shortcuts must use this, not ``engine.position``.
        """
        return float(self._position)

    def is_scrubbing(self) -> bool:
        return bool(self._scrubbing)

    def visible_time_window(self) -> tuple[float, float]:
        """Seconds [start, end] currently visible in the waveform viewport."""
        start = self._time_for_x(float(self._header_width))
        end = self._time_for_x(float(self.width()))
        duration = self._duration()
        return (max(0.0, start), min(duration, max(start + 0.01, end)))

    def set_position(self, seconds: float) -> None:
        if self._scrubbing:
            # Playhead is owned by the scrub gesture; ignore engine ticks so
            # a delayed seek cannot yank the line away from the cursor.
            return
        self._position = seconds
        scroll_moved = False
        if self._auto_scroll:
            prev_scroll = self._scroll_x
            if self._view_pinned:
                # Keep a click-seek / scrub pin until the playhead leaves the
                # visible waveform; then auto-follow again (no wheel needed).
                if self._playing and self._playhead_outside_view(margin=48.0):
                    self._view_pinned = False
                    self._follow_playhead()
            else:
                self._follow_playhead()
            scroll_moved = abs(self._scroll_x - prev_scroll) > 0.5
            # While playing/scrubbing, keep the static backdrop and blit it with
            # a scroll offset (see paintEvent). Invalidating here forced a full
            # waveform rebuild every tick at the follow edge → visible jitter.
            if scroll_moved and not (self._playing or self._scrubbing):
                self._invalidate_scrub_backdrop()
        if self._playing:
            now = monotonic_ns()
            # Playhead-only blit stays ~60 Hz; backdrop rebuild is rare now that
            # auto-scroll no longer invalidates every edge tick.
            interval = 16_000_000
            if scroll_moved or now - self._last_play_repaint_ns >= interval:
                self._last_play_repaint_ns = now
                self.update()
        else:
            self.update()
        self.view_changed.emit()

    def set_zoom(self, pixels_per_second: float, anchor_x: float | None = None) -> None:
        lo = self._min_pixels_per_second()
        new_pps = max(lo, min(4000.0, pixels_per_second))
        if self._view_pinned:
            # Keep the time under the given (or view-center) x stable — don't snap playhead.
            if anchor_x is None:
                anchor_x = self._header_width + self._view_width() * 0.5
            anchor_x = max(float(self._header_width), float(anchor_x))
            anchor_time = self._time_for_x(anchor_x)
            self._pixels_per_second = new_pps
            self._scroll_x = anchor_time * self._pixels_per_second - (anchor_x - self._header_width)
            self._clamp_scroll()
        else:
            self._pixels_per_second = new_pps
            self._center_on_playhead()
        self._invalidate_scrub_backdrop()
        self.update()
        self.view_changed.emit()

    def zoom_by(self, factor: float, anchor_x: float | None = None) -> None:
        self.set_zoom(self._pixels_per_second * factor, anchor_x=anchor_x)

    def fit_to_view(self) -> None:
        """Zoom out so the whole song fits in one screen."""
        self._view_pinned = False
        self._pixels_per_second = self._min_pixels_per_second()
        self._scroll_x = 0.0
        self._invalidate_scrub_backdrop()
        self.update()
        self.view_changed.emit()

    def _release_view_pin(self, *, center_now: bool = True) -> None:
        """First scroll after a click-seek: allow centering again."""
        if not self._view_pinned:
            return
        self._view_pinned = False
        if center_now:
            self._center_on_playhead()

    def _min_pixels_per_second(self) -> float:
        view = max(1.0, self.width() - self._header_width)
        duration = max(0.1, self._duration())
        # Zoom-out stops when the whole song fits in the visible waveform width.
        return max(0.25, view / duration)

    def set_wave_height(self, height: int) -> None:
        """Grow / shrink waveform; mark lanes get narrower as wave grows."""
        self._wave_height = self._clamp_wave_height(height)
        self._apply_layout_heights()
        self.update()

    def _wave_bottom_y(self) -> int:
        return self._ruler_height + self._wave_height

    def _video_band_height(self) -> int:
        """Canvas height for the Video lane (0 when hidden — eye stays in header only)."""
        if self._video_lane_visible():
            return int(self._video_lane_height)
        return 0

    def _apply_layout_heights(self) -> None:
        # setMinimumHeight can re-enter via resizeEvent; skip nested applies so
        # eye-toggle / song-switch cannot recurse into a stack overflow.
        if getattr(self, "_applying_layout_heights", False):
            return
        self._applying_layout_heights = True
        try:
            self._apply_layout_heights_inner()
        finally:
            self._applying_layout_heights = False

    def _apply_layout_heights_inner(self) -> None:
        # Taller wave → thinner lane rows only when no song height is stored.
        max_h = max(80, self._max_wave_height())
        self._wave_height = max(80, min(max_h, self._wave_height))
        self._lane_height = self._clamp_mark_lane_height(self._project_mark_lane_height)
        video_h = self._video_band_height()
        ltc_h = self._ltc_band_height()
        needed = (
            self._ruler_height
            + self._wave_height
            + int(self._music_chrome_extra())
            + ltc_h
            + video_h
            + self._marks_band_height()
            + 8
        )
        changed = needed != self._content_height
        self._content_height = needed
        self.setMinimumHeight(needed)
        self._layout_video_track_overlay()
        self._layout_music_header_overlay()
        # Only notify when height actually changes — otherwise drag-resize
        # (resizeEvent → apply → emit → parent resize → …) can recurse until crash.
        if not changed:
            return
        # While dragging a splitter, skip the parent scroll sync signal — the
        # mouse-move path already updated min/content height; emitting causes
        # viewport scrollbar churn that re-enters layout and can stack-overflow.
        if self._resizing_wave or self._resizing_video_lane or self._resizing_mark_lanes:
            self._geometry_sync_pending = True
            # Grow/shrink locally so the drag still feels live without going
            # through MainWindow → QScrollArea → resizeEvent feedback.
            target_h = max(self.minimumHeight(), self._content_height)
            if self.height() != target_h:
                was_busy = getattr(self, "_layout_heights_busy", False)
                self._layout_heights_busy = True
                try:
                    self.resize(self.width(), target_h)
                finally:
                    self._layout_heights_busy = was_busy
            return
        self.content_geometry_changed.emit()

    def _max_wave_height(self) -> int:
        # Independent from video/mark lanes — tall content scrolls in the parent.
        return 2400

    def _clamp_wave_height(self, height: int | float) -> int:
        return max(80, min(self._max_wave_height(), int(height)))

    def _near_wave_split(self, y: float) -> bool:
        return abs(y - self._wave_bottom_y()) <= self._wave_split_hit

    def _in_waveform(self, x: float, y: float) -> bool:
        """Seek / scrub inside the waveform pane (not header or mark tracks)."""
        if x < self._header_width:
            return False
        top = self._ruler_height
        bottom = self._wave_bottom_y() - self._wave_split_hit
        return top <= y < bottom

    def _in_scrub_zone(self, x: float, y: float) -> bool:
        """Waveform or time ruler — both allow precise scrubbing."""
        if x < self._header_width:
            return False
        if y < self._ruler_height:
            return True
        return self._in_waveform(x, y)

    def set_lane_visible(self, lane_index: int, visible: bool) -> None:
        if self._song is None:
            return
        lane = self._song.lane_by_index(lane_index)
        if lane is None:
            return
        lane.visible = visible
        self._apply_layout_heights()
        self._invalidate_scrub_backdrop()
        self.marks_changed.emit()
        self.content_geometry_changed.emit()
        self.update()

    def resizeEvent(self, event) -> None:  # noqa: ANN001
        super().resizeEvent(event)
        # Floating zoom / video chrome must always track the widget width.
        # MainWindow._sync_timeline_geometry sets ``_layout_heights_busy`` while
        # calling ``resize()`` so height clamping does not re-enter — that used
        # to skip overlay layout entirely, leaving A/zoom/fit stuck mid-widget
        # until something else (e.g. Video eye toggle) re-laid them out.
        if getattr(self, "_layout_heights_busy", False):
            self._layout_zoom_overlay()
            self._layout_video_track_overlay()
            return
        self._layout_heights_busy = True
        try:
            clamped = self._clamp_wave_height(self._wave_height)
            if clamped != self._wave_height:
                self._wave_height = clamped
            lane_clamped = self._clamp_video_lane_height(self._video_lane_base_height)
            if lane_clamped != self._video_lane_base_height:
                self._video_lane_base_height = lane_clamped
                if self._song is not None:
                    self._song.video_lane_height = lane_clamped
            self._apply_layout_heights()
            self._layout_zoom_overlay()
            self._layout_video_track_overlay()
        finally:
            self._layout_heights_busy = False

    def _duration(self) -> float:
        if self._audio is not None:
            return max(0.1, self._audio.duration_seconds)
        if self._song is None:
            return 60.0
        return max(1.0, self._song.duration_seconds)

    def _content_width(self) -> float:
        return self._duration() * self._pixels_per_second

    def _max_scroll(self) -> float:
        view = max(0.0, self.width() - self._header_width)
        return max(0.0, self._content_width() - view)

    def _clamp_scroll(self) -> None:
        self._scroll_x = min(max(0.0, self._scroll_x), self._max_scroll())

    def _view_width(self) -> float:
        return max(1.0, self.width() - self._header_width)

    def transport_anchor_global_point(self) -> QPointF | None:
        """Horizontal center of the visible waveform pane (excludes Mark Type header)."""
        view_w = self._view_width()
        if view_w <= 8:
            return None
        x = float(self._header_width) + view_w / 2.0
        y = self.height() / 2.0
        return self.mapToGlobal(QPointF(x, y))

    def _center_on_playhead(self) -> None:
        """Keep playhead in the horizontal middle of the waveform view."""
        target = self._view_width() * 0.5
        self._scroll_x = self._position * self._pixels_per_second - target
        self._clamp_scroll()

    def _follow_playhead(self) -> None:
        """Keep the playhead on-screen without recentering every tick.

        Continuous centering forces ``scroll_x`` to change every frame.
        Edge-band follow only scrolls when the playhead leaves ~25%–75% of the
        view, then parks it on that edge so follow feels continuous.

        Waveform stays filled via an overscanned play-cache (see
        ``_blit_scrub_backdrop``); scroll is quantized to whole pixels so the
        blit source does not shimmer by ±1 px each tick.
        """
        if not self._playing:
            self._center_on_playhead()
            return
        view_w = self._view_width()
        if view_w <= 1.0:
            return
        x = self._x_for_time(self._position)
        left = float(self._header_width) + view_w * 0.25
        right = float(self._header_width) + view_w * 0.75
        if x < left:
            self._scroll_x = round(
                self._position * self._pixels_per_second - view_w * 0.25
            )
            self._clamp_scroll()
        elif x > right:
            self._scroll_x = round(
                self._position * self._pixels_per_second - view_w * 0.75
            )
            self._clamp_scroll()

    def _playhead_outside_view(self, *, margin: float = 0.0) -> bool:
        """True when the playhead is outside the waveform viewport (+ margin)."""
        x = self._x_for_time(self._position)
        left = float(self._header_width) + float(margin)
        right = float(self.width()) - float(margin)
        return x < left or x > right

    def _x_for_time(self, seconds: float) -> float:
        return self._header_width + seconds * self._pixels_per_second - self._scroll_x

    def _time_for_x(self, x: float) -> float:
        return max(0.0, (x - self._header_width + self._scroll_x) / self._pixels_per_second)

    def _seek_from_x(self, x: float) -> None:
        x = min(max(x, float(self._header_width)), float(self.width()))
        self.seek_requested.emit(min(self._time_for_x(x), self._duration()))

    def _scrub_at(self, x: float, *, force: bool = False) -> None:
        """Move playhead under cursor; pan view near left/right edges.

        Timeline paint stays on the cached backdrop. Engine seek / LTC /
        MTC only run on force (press + release). Preview/Clean get a
        throttled scrub_preview_requested so video still follows the drag.
        """
        prev_scroll = self._scroll_x
        view_w = self._view_width()
        local = x - self._header_width
        edge = self._scrub_edge
        if local < edge:
            self._scroll_x -= max(4.0, (edge - local) * 0.45)
        elif local > view_w - edge:
            self._scroll_x += max(4.0, (local - (view_w - edge)) * 0.45)
        self._clamp_scroll()

        self._position = min(self._time_for_x(x), self._duration())
        now_ms = monotonic_ns() // 1_000_000
        # ~24 Hz — scrub posters are cache lookups; keep Preview following.
        if force or now_ms - self._last_scrub_preview_ms >= 40:
            self._last_scrub_preview_ms = now_ms
            self.scrub_preview_requested.emit(self._position)
        if force:
            self._seek_from_x(x)
        if abs(self._scroll_x - prev_scroll) > 0.5:
            self._invalidate_scrub_backdrop()
        self.update()
        self.view_changed.emit()

    def _paint_right(self) -> int:
        """Right edge used by static-layer painters (may be wider during overscan bake)."""
        if self._paint_width_override is not None:
            return int(self._paint_width_override)
        return int(self.width())

    def _invalidate_scrub_backdrop(self) -> None:
        self._scrub_backdrop = None
        self._scrub_backdrop_overscan = 0

    def invalidate_static_layers(self) -> None:
        """Drop the play/scrub pixmap cache (waveform/video/lanes).

        Marks and gain overlays paint live in ``paintEvent`` — they do not need
        a backdrop rebuild when only marks change.
        """
        self._invalidate_scrub_backdrop()

    def _scrub_backdrop_geometry_ok(self) -> bool:
        """True when the cached backdrop matches zoom + widget size (scroll may drift)."""
        pm = self._scrub_backdrop
        if pm is None or pm.isNull():
            return False
        if self._scrub_backdrop_overscan < 0:
            return False
        return (
            abs(self._pixels_per_second - self._scrub_backdrop_pps) < 1e-6
            and self._scrub_backdrop_size == self.size()
        )

    def _scrub_backdrop_valid(self) -> bool:
        """Exact match including scroll — used when a pixel-perfect cache is required."""
        if not self._scrub_backdrop_geometry_ok():
            return False
        return abs(self._scroll_x - self._scrub_backdrop_scroll) < 0.5

    def _blit_scrub_backdrop(self, painter: QPainter) -> bool:
        """Draw the static cache, shifting within an overscanned bake.

        Auto-scroll used to offset a viewport-sized pixmap, which left a growing
        black gap on the newly exposed side. The cache is now wider than the
        view; we only rebuild when scroll leaves the overscan margin.
        """
        if not self._scrub_backdrop_geometry_ok():
            self._rebuild_scrub_backdrop()
        if not self._scrub_backdrop_geometry_ok():
            return False

        overscan = int(self._scrub_backdrop_overscan)
        delta = int(round(self._scroll_x - self._scrub_backdrop_scroll))
        # Rebuild with a small margin so the gap never flashes black.
        margin = 8
        if delta < -overscan + margin or delta > overscan - margin:
            self._rebuild_scrub_backdrop()
            if not self._scrub_backdrop_geometry_ok():
                return False
            overscan = int(self._scrub_backdrop_overscan)
            delta = 0

        pm = self._scrub_backdrop
        assert pm is not None
        w = self.width()
        h = self.height()
        hw = int(self._header_width)
        content_w = max(0, w - hw)
        src_x = hw + overscan + delta

        painter.fillRect(0, 0, w, h, QColor(BG_APP))
        # Content region — sample the matching strip from the wide cache.
        painter.save()
        painter.setClipRect(hw, 0, content_w, h)
        painter.drawPixmap(hw, 0, pm, src_x, 0, content_w, h)
        painter.restore()
        # Header column stays fixed (baked at x=0 in the cache).
        painter.save()
        painter.setClipRect(0, 0, hw, h)
        painter.drawPixmap(0, 0, pm, 0, 0, hw, h)
        painter.restore()
        return True

    def _rebuild_scrub_backdrop(self) -> None:
        """Rasterize static timeline layers once; scrub/play only redraw playhead."""
        if self.width() <= 0 or self.height() <= 0:
            self._scrub_backdrop = None
            self._scrub_backdrop_overscan = 0
            return
        # Match paintEvent: QPainter(QPixmap) defaults to QApplication.font(),
        # not the stylesheet-resolved widget font (theme sets 13px on QWidget).
        # Without copying self.font(), ruler/lane/header text looks smaller for
        # the whole scrub gesture and snaps back on mouse-up.
        overscan = max(64, int(self._view_width() * 0.75))
        paint_w = int(self.width()) + 2 * overscan
        saved_scroll = self._scroll_x
        # Bake content for [scroll - overscan, scroll + view + overscan].
        self._scroll_x = saved_scroll - float(overscan)
        self._paint_width_override = paint_w
        try:
            dpr = max(1.0, float(self.devicePixelRatioF()))
            pm = QPixmap(int(paint_w * dpr), int(self.height() * dpr))
            pm.setDevicePixelRatio(dpr)
            pm.fill(QColor(BG_APP))
            painter = QPainter(pm)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
            painter.setFont(self.font())
            self._paint_static_layers(painter)
            painter.end()
        finally:
            self._scroll_x = saved_scroll
            self._paint_width_override = None
        self._scrub_backdrop = pm
        self._scrub_backdrop_scroll = saved_scroll
        self._scrub_backdrop_pps = self._pixels_per_second
        self._scrub_backdrop_size = QSize(self.size())
        self._scrub_backdrop_overscan = overscan

    def _can_use_static_backdrop(self) -> bool:
        """Playhead-only blit while scrubbing or playing (no live edit overlays)."""
        if self._box_selecting or self._dragging_marks or self._dragging_clip is not None:
            return False
        if self._trimming_clip is not None:
            return False
        if self._dragging_audio_gain:
            return False
        if self._resizing_wave or self._resizing_video_lane or self._resizing_mark_lanes or self._panning:
            return False
        return self._scrubbing or self._playing

    def _paint_static_layers(self, painter: QPainter) -> None:
        self._paint_ruler(painter)
        wave_bottom = self._paint_waveform(painter)
        self._paint_video_lane(painter)
        self._paint_ltc_lane(painter)
        tracks_top = self._tracks_top_y()
        self._paint_lanes(painter, start_y=tracks_top)
        # Marks paint live in paintEvent (play/scrub + edit paths).
        # Loop region is painted live in paintEvent (play/scrub path) so A/B
        # taps mid-playback stay visible without rebuilding the backdrop.
        self._paint_wave_splitter(painter, wave_bottom)
        self._paint_video_lane_splitter(painter)
        self._paint_mark_lane_splitter(painter)
        # Gain lines are interactive — paint live in paintEvent (not baked here).
        self._paint_selection_box(painter)
        painter.fillRect(0, 0, self._header_width, self.height(), QColor("#111113"))
        self._paint_headers(painter, wave_bottom, tracks_top)

    def _scrub_tick(self) -> None:
        if not self._scrubbing:
            self._scrub_timer.stop()
            return
        pos = self.mapFromGlobal(QCursor.pos())
        # Only keep the timer for edge auto-pan while held still (visual
        # scroll + playhead). Engine seek waits for mouse-up.
        view_w = self._view_width()
        local = pos.x() - self._header_width
        if local < self._scrub_edge or local > view_w - self._scrub_edge:
            self._scrub_at(pos.x(), force=False)

    def _hit_mark_at(self, x: float, y: float) -> str | None:
        """Return mark id under cursor on tracks or waveform overlay lines."""
        if self._song is None or x < self._header_width:
            return None

        best_id: str | None = None
        best_dist = self._mark_hit_radius

        if self._in_mark_tracks(x, y) and self._show_mark_tracks:
            lane_rects = {idx: (y0, y1) for idx, y0, y1 in self._lane_rects()}
            for mark in self._song.marks:
                pair = lane_rects.get(mark.lane_index)
                if pair is None:
                    continue
                y0, y1 = pair
                if y < y0 or y > y1:
                    continue
                mx = self._x_for_time(mark.time_seconds)
                dist = abs(mx - x)
                if dist <= best_dist:
                    best_dist = dist
                    best_id = mark.id
            return best_id

        # Waveform / ruler: grab any mark by its vertical line (precise wave editing).
        if self._in_scrub_zone(x, y):
            for mark in self._song.marks:
                lane = self._song.lane_by_index(mark.lane_index)
                if lane is not None and not lane.visible:
                    continue
                mx = self._x_for_time(mark.time_seconds)
                dist = abs(mx - x)
                if dist <= best_dist:
                    best_dist = dist
                    best_id = mark.id
        return best_id

    def _begin_mark_interaction(
        self,
        hit_id: str,
        x: float,
        y: float,
        *,
        shift: bool,
        ctrl: bool,
    ) -> None:
        """Select / prepare drag. Seek only on click-release if not dragged."""
        self.setFocus(Qt.FocusReason.MouseFocusReason)
        mark = self._song.mark_by_id(hit_id) if self._song else None
        if mark is None:
            return
        if ctrl:
            ids = set(self._selected_mark_ids)
            if hit_id in ids:
                ids.discard(hit_id)
            else:
                ids.add(hit_id)
            self.set_selected_mark_ids(ids)
            self._pending_single_select = None
        elif shift:
            ids = set(self._selected_mark_ids)
            ids.add(hit_id)
            self.set_selected_mark_ids(ids)
            self._pending_single_select = None
        else:
            if hit_id in self._selected_mark_ids and len(self._selected_mark_ids) > 1:
                # Keep multi-select for a possible group drag; collapse on click-release.
                self._pending_single_select = hit_id
            else:
                self.set_selected_mark_ids([hit_id])
                self._pending_single_select = None

        # Defer seek until release if this stays a click (no drag).
        self._drag_click_seek = mark.time_seconds

        lane = self._song.lane_by_index(mark.lane_index) if self._song else None
        if lane is not None and lane.locked:
            self.update()
            return
        # Always allow click-seek / select; only Setup mode arms time dragging.
        if hit_id in self._selected_mark_ids and len(self._selected_mark_ids) > 1:
            self._drag_ids = set(self._selected_mark_ids)
        else:
            self._drag_ids = {hit_id}
        self._drag_start_times = {}
        for mid in self._drag_ids:
            m = self._song.mark_by_id(mid) if self._song else None
            if m is not None:
                self._drag_start_times[mid] = m.time_seconds
        self._dragging_marks = True
        self._drag_moved = False
        self._drag_origin_x = x
        self._view_pinned = True
        self.grabMouse()
        self.setCursor(self._cursor_for_mark_hover(x, y))
        self.update()

    def _begin_video_clip_interaction(
        self,
        clip_id: str,
        zone: str,
        x: float,
        *,
        shift: bool,
        ctrl: bool,
    ) -> None:
        if self._song is None:
            return
        clip = self._song.video_clip_by_id(clip_id)
        if clip is None:
            return
        if ctrl:
            ids = set(self._selected_clip_ids)
            ids.symmetric_difference_update({clip_id})
            self.set_selected_video_clip_ids(ids)
        elif shift and not clip.locked:
            self.set_selected_video_clip_ids(set(self._selected_clip_ids) | {clip_id})
        else:
            self.set_selected_video_clip_ids([clip_id])

        # Locked clips: Shift temporarily frees move/trim (stays locked after).
        if clip.locked and not shift:
            self.update()
            return

        self._clip_drag_snapshot = {
            clip_id: (clip.start_seconds, clip.source_in_seconds, clip.duration_seconds)
        }
        self._clip_drag_origin_x = x
        self._clip_drag_moved = False
        self._video_gesture_active = True
        self._view_pinned = True
        self.grabMouse()
        if zone in ("left", "right"):
            self._trimming_clip = (clip_id, zone)
        else:
            self._dragging_clip = clip_id
        self.setCursor(Qt.CursorShape.SizeHorCursor if zone in ("left", "right") else Qt.CursorShape.ClosedHandCursor)
        self.update()

    def _update_video_clip_drag(self, x: float, *, snap: bool = True) -> None:
        if self._song is None or self._dragging_clip is None:
            return
        clip = self._song.video_clip_by_id(self._dragging_clip)
        snapshot = self._clip_drag_snapshot.get(self._dragging_clip)
        if clip is None or snapshot is None:
            return
        dx = x - self._clip_drag_origin_x
        if abs(dx) >= self._drag_slop:
            self._clip_drag_moved = True
        if not self._clip_drag_moved:
            return
        start0, _src_in0, dur0 = snapshot
        dt = dx / max(1e-6, self._pixels_per_second)
        clip.start_seconds = clip_start_after_body_drag(start0, dt, snap=snap)
        self._update_video_lane()

    def _update_video_clip_trim(self, x: float) -> None:
        if self._song is None or self._trimming_clip is None:
            return
        clip_id, zone = self._trimming_clip
        clip = self._song.video_clip_by_id(clip_id)
        snapshot = self._clip_drag_snapshot.get(clip_id)
        if clip is None or snapshot is None:
            return
        dx = x - self._clip_drag_origin_x
        if abs(dx) >= self._drag_slop:
            self._clip_drag_moved = True
        if not self._clip_drag_moved:
            return
        start0, src_in0, dur0 = snapshot
        dt = dx / max(1e-6, self._pixels_per_second)
        min_dur = 0.05
        if zone == "left":
            delta = min(max(dt, -start0), dur0 - min_dur)
            delta = max(delta, -src_in0)  # can't trim in before the source's own start
            clip.start_seconds = start0 + delta
            clip.source_in_seconds = src_in0 + delta
            clip.duration_seconds = dur0 - delta
        else:
            clip.duration_seconds = clip_duration_after_right_trim(
                dur0,
                dt,
                source_in_seconds=src_in0,
                source_duration_seconds=clip.source_duration_seconds,
            )
        clip.source_out_seconds = clip.source_in_seconds + clip.duration_seconds
        self._update_video_lane()

    def _end_video_clip_gesture(self) -> None:
        """Shared release-time bookkeeping for both drag-move and trim gestures."""
        clip_id = self._dragging_clip or (self._trimming_clip[0] if self._trimming_clip else None)
        moved = self._clip_drag_moved
        self._dragging_clip = None
        self._trimming_clip = None
        self._clip_drag_moved = False
        self._video_gesture_active = False
        if clip_id and moved and self._song is not None:
            clip = self._song.video_clip_by_id(clip_id)
            old = self._clip_drag_snapshot.get(clip_id)
            if clip is not None and old is not None:
                new = (clip.start_seconds, clip.source_in_seconds, clip.duration_seconds)
                self._song.sort_video_clips()
                if any(abs(a - b) > 1e-6 for a, b in zip(old, new)):
                    self.video_clip_edited.emit(clip_id, old, new)
                self.video_clips_changed.emit()
        self._clip_drag_snapshot = {}

    def _nudge_video_clips(self, clip_ids: list[str], delta_seconds: float) -> None:
        if self._song is None:
            return
        changes: dict[str, tuple[tuple[float, float, float], tuple[float, float, float]]] = {}
        for clip_id in clip_ids:
            clip = self._song.video_clip_by_id(clip_id)
            if clip is None or clip.locked:
                continue
            old = (clip.start_seconds, clip.source_in_seconds, clip.duration_seconds)
            new_start = clip_start_after_body_drag(clip.start_seconds, delta_seconds)
            if abs(new_start - clip.start_seconds) < 1e-9:
                continue
            clip.start_seconds = new_start
            changes[clip_id] = (old, (clip.start_seconds, clip.source_in_seconds, clip.duration_seconds))
        if changes:
            self._song.sort_video_clips()
            self.video_clips_batch_edited.emit(changes)
            self.update()

    def _show_video_clip_context_menu(self, pos, x: float, y: float) -> None:  # noqa: ANN001
        if self._song is None:
            return
        hit = self._hit_video_clip(x, y)
        menu = QMenu(self)
        time_here = self._time_for_x(x)
        if hit is None:
            add_action = menu.addAction("Add Video Clip Here…")
            hide_track_action = menu.addAction("Hide Video / LTC Tracks")
            hide_track_action.setToolTip(
                "Collapse Video + LTC lanes after alignment — Preview/Clean Output keep playing"
            )
            chosen = menu.exec(self.mapToGlobal(pos))
            if chosen is add_action:
                self.add_video_clip_requested.emit(time_here)
            elif chosen is hide_track_action:
                self.set_show_video_track(False)
            return

        clip_id, _zone = hit
        clip = self._song.video_clip_by_id(clip_id)
        if clip is None:
            return
        if clip_id not in self._selected_clip_ids:
            self.set_selected_video_clip_ids([clip_id])
        ids = list(self._selected_clip_ids)

        lock_action = menu.addAction("Unlock" if clip.locked else "Lock")
        lock_action.setToolTip(
            "Unlock this clip"
            if clip.locked
            else "Lock this clip (Shift+drag temporarily frees move/trim)"
        )
        hide_action = menu.addAction("Show" if clip.hidden else "Hide")
        menu.addSeparator()
        hide_track_action = menu.addAction("Hide Video / LTC Tracks")
        menu.addSeparator()
        can_split = clip.start_seconds + 0.02 < self._position < clip.end_seconds - 0.02
        split_action = menu.addAction("Split at Playhead")
        split_action.setEnabled(can_split and len(ids) == 1)
        duplicate_action = menu.addAction("Duplicate")
        duplicate_action.setEnabled(len(ids) == 1)
        menu.addSeparator()
        frame = 1.0 / max(1.0, float(self._song.fps or 30.0))
        quick: list[tuple[object, float]] = []
        for label, delta in (
            (f"+1 frame ({frame:.3f}s)", frame),
            (f"-1 frame (-{frame:.3f}s)", -frame),
            ("+0.100s", 0.1),
            ("-0.100s", -0.1),
            ("+1.000s", 1.0),
            ("-1.000s", -1.0),
        ):
            act = menu.addAction(label)
            quick.append((act, delta))
        menu.addSeparator()
        delete_action = menu.addAction(f"Delete Clip(s) ({len(ids)})")

        chosen = menu.exec(self.mapToGlobal(pos))
        if chosen is None:
            return
        if chosen is hide_track_action:
            self.set_show_video_track(False)
            return
        if chosen is lock_action:
            new_locked = not clip.locked
            for cid in ids:
                c = self._song.video_clip_by_id(cid)
                if c is not None:
                    c.locked = new_locked
            self.video_clips_changed.emit()
            self.update()
            return
        if chosen is hide_action:
            new_hidden = not clip.hidden
            for cid in ids:
                c = self._song.video_clip_by_id(cid)
                if c is not None:
                    c.hidden = new_hidden
            self.video_clips_changed.emit()
            self.update()
            return
        if chosen is split_action:
            self.split_video_clip_requested.emit(clip_id, self._position)
            return
        if chosen is duplicate_action:
            self.duplicate_video_clip_requested.emit(clip_id)
            return
        if chosen is delete_action:
            self.delete_video_clips_requested.emit(ids)
            return
        for act, delta in quick:
            if chosen is act:
                self._nudge_video_clips(ids, delta)
                return

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:  # noqa: N802
        if mime_looks_like_file_drop(event.mimeData()):
            accept_file_drag(event)
        else:
            event.ignore()

    def dragMoveEvent(self, event: QDragMoveEvent) -> None:  # noqa: N802
        if mime_looks_like_file_drop(event.mimeData()):
            accept_file_drag(event)
        else:
            event.ignore()

    def dropEvent(self, event: QDropEvent) -> None:  # noqa: N802
        paths = video_paths_from_mime(event.mimeData())
        if not paths:
            event.ignore()
            return
        accept_file_drop(event)
        drop_time = self._time_for_x(event.position().x())
        self.video_files_dropped.emit(paths, drop_time)

    def _video_lane_dirty_rect(self) -> QRect:
        top = self._video_lane_top_y()
        bottom = self._ltc_lane_top_y() + self._ltc_band_height()
        return QRect(0, top, self.width(), max(1, bottom - top))

    def _update_video_lane(self) -> None:
        self.update(self._video_lane_dirty_rect())

    def mousePressEvent(self, event) -> None:  # noqa: ANN001
        x = event.position().x()
        y = event.position().y()
        if event.button() == Qt.MouseButton.LeftButton:
            shift = bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
            ctrl = bool(
                event.modifiers()
                & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.MetaModifier)
            )
            alt = bool(event.modifiers() & Qt.KeyboardModifier.AltModifier)
            # Alt+left still pans even in box-select mode.
            if alt and x >= self._header_width:
                self._begin_pan(x)
                return
            if self._near_wave_split(y):
                self._resizing_wave = True
                self.grabMouse()
                self.setCursor(Qt.CursorShape.SizeVerCursor)
            elif self._near_video_lane_split(y):
                self._resizing_video_lane = True
                self.grabMouse()
                self.setCursor(Qt.CursorShape.SizeVerCursor)
            elif self._near_mark_lane_split(y):
                self._resizing_mark_lanes = True
                self.grabMouse()
                self.setCursor(Qt.CursorShape.SizeVerCursor)
            elif (gain_zone := self._near_audio_gain_line(x, y)) is not None:
                self._dragging_audio_gain = True
                self._audio_gain_zone = gain_zone
                if gain_zone == "wave":
                    self._audio_gain_drag_bounds = self._wave_gain_travel_bounds()
                else:
                    self._audio_gain_drag_bounds = self._ltc_gain_travel_bounds()
                self._invalidate_scrub_backdrop()
                self.grabMouse()
                self.setCursor(Qt.CursorShape.SizeVerCursor)
                self._apply_gain_at_y(y, gain_zone)
            elif (lane_index := self._hit_mark_lane_header(x, y)) is not None:
                self.setFocus(Qt.FocusReason.MouseFocusReason)
                self.add_mark_requested.emit(lane_index)
                return
            elif (loop_h := self._hit_loop_handle(x, y)) is not None:
                # Click seeks to A/B; drag always moves the loop point.
                self._dragging_loop = loop_h
                self._loop_drag_moved = False
                self._loop_drag_origin_x = x
                self._view_pinned = True
                self.grabMouse()
                self.setCursor(self._cursor_for_loop_hover(x, y))
                self.setFocus(Qt.FocusReason.MouseFocusReason)
                self.update()
            elif (hit_id := self._hit_mark_at(x, y)) is not None:
                self._begin_mark_interaction(hit_id, x, y, shift=shift, ctrl=ctrl)
            elif (clip_hit := self._hit_video_clip(x, y, allow_locked_edit=shift)) is not None:
                self.setFocus(Qt.FocusReason.MouseFocusReason)
                self._begin_video_clip_interaction(
                    clip_hit[0], clip_hit[1], x, shift=shift, ctrl=ctrl
                )
            elif self._in_video_lane(x, y):
                self.setFocus(Qt.FocusReason.MouseFocusReason)
                if not (shift or ctrl):
                    self.set_selected_video_clip_ids([])
            elif self._box_select_mode and (
                self._in_mark_tracks(x, y) or self._in_scrub_zone(x, y) or shift
            ):
                self._begin_box_select(
                    event.position(),
                    additive=ctrl,
                    click_seek=self._time_for_x(x) if self._in_scrub_zone(x, y) else None,
                )
            elif self._in_scrub_zone(x, y):
                # Left-drag scrubs the playhead so time follows the cursor.
                self.clear_selection()
                self._scrubbing = True
                self._view_pinned = True
                self._invalidate_scrub_backdrop()
                self.scrub_started.emit()
                self.grabMouse()
                self._scrub_at(x, force=True)
                self._scrub_timer.start()
                self.setCursor(Qt.CursorShape.ArrowCursor)
            elif self._in_mark_tracks(x, y):
                self.clear_selection()
            elif x >= self._header_width:
                self.clear_selection()
        elif event.button() == Qt.MouseButton.MiddleButton:
            if x >= self._header_width:
                self._begin_pan(x)
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: ANN001
        y = event.position().y()
        x = event.position().x()
        pan_buttons = Qt.MouseButton.LeftButton | Qt.MouseButton.MiddleButton
        if self._panning and event.buttons() & pan_buttons:
            dx = x - self._pan_origin_x
            if abs(dx) >= self._drag_slop:
                self._pan_moved = True
                self._pan_click_seek = None
            if self._pan_moved:
                self._scroll_x = self._pan_origin_scroll - dx
                self._clamp_scroll()
                self._invalidate_scrub_backdrop()
                self.update()
                self.view_changed.emit()
        elif self._dragging_loop is not None and event.buttons() & Qt.MouseButton.LeftButton:
            dx = x - self._loop_drag_origin_x
            if abs(dx) >= self._drag_slop:
                self._loop_drag_moved = True
            if self._loop_drag_moved:
                self._set_loop_handle_time(self._dragging_loop, self._time_for_x(x))
        elif self._resizing_wave and event.buttons() & Qt.MouseButton.LeftButton:
            new_h = y - self._ruler_height
            self.set_wave_height(new_h)
        elif self._resizing_video_lane and event.buttons() & Qt.MouseButton.LeftButton:
            new_h = y - self._video_lane_top_y()
            self.set_video_lane_height(new_h)
        elif self._resizing_mark_lanes and event.buttons() & Qt.MouseButton.LeftButton:
            n = max(1, self._visible_lane_count())
            total = y - self._tracks_top_y() - self._mark_lane_split_h
            gap_total = max(0, n - 1) * self._mark_lane_gap_px()
            self.set_mark_lane_height((total - gap_total) / n)
        elif self._dragging_audio_gain and event.buttons() & Qt.MouseButton.LeftButton:
            zone = self._audio_gain_zone or "wave"
            self._apply_gain_at_y(y, zone)
        elif self._dragging_marks and event.buttons() & Qt.MouseButton.LeftButton:
            dx = x - self._drag_origin_x
            if abs(dx) >= self._drag_slop and self._setup_mode:
                self._drag_moved = True
                self._drag_click_seek = None
                self._pending_single_select = None
            if self._drag_moved and self._song is not None:
                dt = dx / max(1e-6, self._pixels_per_second)
                duration = self._duration()
                for mid, start_t in self._drag_start_times.items():
                    m = self._song.mark_by_id(mid)
                    if m is None:
                        continue
                    lane = self._song.lane_by_index(m.lane_index)
                    if lane is not None and lane.locked:
                        continue
                    m.time_seconds = min(max(0.0, start_t + dt), duration)
                self.update()
        elif self._dragging_clip is not None and event.buttons() & Qt.MouseButton.LeftButton:
            shift = bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
            self._update_video_clip_drag(x, snap=not shift)
        elif self._trimming_clip is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self._update_video_clip_trim(x)
        elif self._box_selecting and event.buttons() & Qt.MouseButton.LeftButton:
            self._box_current = event.position()
            rect = self._selection_box_rect()
            if rect.width() >= 4 or rect.height() >= 4:
                self._box_click_seek = None
            self._emit_box_preview()
        elif self._scrubbing and event.buttons() & Qt.MouseButton.LeftButton:
            self._scrub_at(x)
        else:
            hover_wave = self._near_wave_split(y)
            hover_video = False if hover_wave else self._near_video_lane_split(y)
            hover_mark = False if (hover_wave or hover_video) else self._near_mark_lane_split(y)
            if hover_wave != self._wave_split_hover:
                self._wave_split_hover = hover_wave
                self.update()
            if hover_video != self._video_lane_split_hover:
                self._video_lane_split_hover = hover_video
                self.update()
            if hover_mark != self._mark_lane_split_hover:
                self._mark_lane_split_hover = hover_mark
                self.update()
            hover = hover_wave or hover_video or hover_mark
            gain_zone = None if hover else self._near_audio_gain_line(x, y)
            if gain_zone != self._hover_audio_gain_zone:
                self._hover_audio_gain_zone = gain_zone
                self.update()
            hit = None if hover else self._hit_mark_at(x, y)
            if hit != self._hover_mark_id:
                self._hover_mark_id = hit
                self.update()
            loop_h = None if hover else self._hit_loop_handle(x, y)
            if loop_h != self._hover_loop:
                self._hover_loop = loop_h
                self.update()
            clip_hit = None if (hover or hit is not None) else self._hit_video_clip(
                x,
                y,
                allow_locked_edit=bool(
                    event.modifiers() & Qt.KeyboardModifier.ShiftModifier
                ),
            )
            clip_hover_id = clip_hit[0] if clip_hit is not None else None
            if clip_hover_id != self._hover_clip_id:
                self._hover_clip_id = clip_hover_id
                self.update()
            header_lane = None if hover else self._hit_mark_lane_header(x, y)
            if header_lane != self._hover_mark_lane_header:
                self._hover_mark_lane_header = header_lane
                self.update()
            if hover:
                self.setCursor(Qt.CursorShape.SizeVerCursor)
            elif gain_zone is not None:
                self.setCursor(Qt.CursorShape.SizeVerCursor)
            elif self._hit_mark_lane_header(x, y) is not None:
                self.setCursor(Qt.CursorShape.PointingHandCursor)
            elif loop_h is not None:
                self.setCursor(self._cursor_for_loop_hover(x, y))
            elif hit is not None:
                self.setCursor(self._cursor_for_mark_hover(x, y))
            elif clip_hit is not None:
                self.setCursor(
                    Qt.CursorShape.SizeHorCursor
                    if clip_hit[1] in ("left", "right")
                    else Qt.CursorShape.OpenHandCursor
                )
            elif self._in_mark_tracks(x, y):
                self.setCursor(
                    Qt.CursorShape.CrossCursor
                    if self._box_select_mode
                    else Qt.CursorShape.ArrowCursor
                )
            elif self._in_scrub_zone(x, y):
                self.setCursor(Qt.CursorShape.ArrowCursor)
            elif not self._scrubbing and not self._resizing_wave and not self._resizing_video_lane and not self._resizing_mark_lanes and not self._box_selecting and not self._panning:
                self.setCursor(Qt.CursorShape.ArrowCursor)
        super().mouseMoveEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: ANN001
        changed = False
        if self._hover_mark_id is not None:
            self._hover_mark_id = None
            changed = True
        if self._hover_mark_lane_header is not None:
            self._hover_mark_lane_header = None
            changed = True
        if self._hover_audio_gain_zone is not None:
            self._hover_audio_gain_zone = None
            changed = True
        if changed:
            self.update()
        super().leaveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: ANN001
        if self._panning and event.button() in (
            Qt.MouseButton.MiddleButton,
            Qt.MouseButton.LeftButton,
        ):
            click_seek = self._pan_click_seek if not self._pan_moved else None
            self._panning = False
            self._pan_moved = False
            self._pan_click_seek = None
            self.releaseMouse()
            if click_seek is not None:
                self.seek_requested.emit(click_seek)
                self._position = click_seek
            self._invalidate_scrub_backdrop()
            self._restore_hover_cursor(event.position().x(), event.position().y())
            self.update()
            super().mouseReleaseEvent(event)
            return
        if event.button() == Qt.MouseButton.LeftButton and self._dragging_loop is not None:
            which = self._dragging_loop
            moved = self._loop_drag_moved
            self._dragging_loop = None
            self._loop_drag_moved = False
            self.releaseMouse()
            if moved:
                self._set_loop_handle_time(which, self._time_for_x(event.position().x()))
            else:
                t = self._loop_a if which == "a" else self._loop_b
                if t is not None:
                    self._view_pinned = True
                    self.seek_requested.emit(float(t))
                    self._position = float(t)
            self._restore_hover_cursor(event.position().x(), event.position().y())
            self.update()
            super().mouseReleaseEvent(event)
            return
        if event.button() == Qt.MouseButton.LeftButton and self._dragging_audio_gain:
            self._dragging_audio_gain = False
            self._audio_gain_zone = None
            self._audio_gain_drag_bounds = None
            self._invalidate_scrub_backdrop()
            self.releaseMouse()
            self._restore_hover_cursor(event.position().x(), event.position().y())
            self.update()
            super().mouseReleaseEvent(event)
            return
        if event.button() == Qt.MouseButton.LeftButton and (
            self._dragging_clip is not None or self._trimming_clip is not None
        ):
            self.releaseMouse()
            self._end_video_clip_gesture()
            self._restore_hover_cursor(event.position().x(), event.position().y())
            self.update()
            super().mouseReleaseEvent(event)
            return
        if event.button() == Qt.MouseButton.LeftButton:
            was_scrub = self._scrubbing
            was_box = self._box_selecting
            was_drag = self._dragging_marks
            was_resize = self._resizing_wave or self._resizing_video_lane or self._resizing_mark_lanes
            drag_moved = self._drag_moved
            click_seek = self._drag_click_seek
            box_click_seek = self._box_click_seek
            self._scrubbing = False
            self._resizing_wave = False
            self._resizing_video_lane = False
            self._resizing_mark_lanes = False
            self._box_selecting = False
            self._dragging_marks = False
            self._drag_click_seek = None
            self._box_click_seek = None
            self._scrub_timer.stop()
            self._invalidate_scrub_backdrop()
            self.releaseMouse()
            if was_resize and self._geometry_sync_pending:
                self._geometry_sync_pending = False
                self.content_geometry_changed.emit()
            if was_scrub:
                self._scrub_at(event.position().x(), force=True)
                self.scrub_ended.emit()
            if was_box:
                rect = self._selection_box_rect()
                moved = rect.width() >= 4 or rect.height() >= 4
                if not moved and box_click_seek is not None:
                    self.clear_selection()
                    self._view_pinned = True
                    self.seek_requested.emit(box_click_seek)
                    self._position = box_click_seek
                else:
                    self._box_current = event.position()
                    self._emit_box_preview()
                    self.selection_changed.emit(list(self._selected_mark_ids))
            if was_drag and not drag_moved and click_seek is not None:
                self.seek_requested.emit(click_seek)
                self._position = click_seek
                if self._pending_single_select is not None:
                    self.set_selected_mark_ids([self._pending_single_select])
            if was_drag and drag_moved and self._song is not None:
                moved_times: dict[str, tuple[float, float]] = {}
                for mid, start_t in self._drag_start_times.items():
                    mark = self._song.mark_by_id(mid)
                    if mark is None:
                        continue
                    if abs(mark.time_seconds - start_t) >= 1e-6:
                        moved_times[mid] = (start_t, mark.time_seconds)
                self._song.sort_marks()
                if moved_times:
                    self.marks_moved.emit(moved_times)
                self.marks_changed.emit()
                self.selection_changed.emit(list(self._selected_mark_ids))
            self._drag_ids.clear()
            self._drag_start_times.clear()
            self._drag_moved = False
            self._pending_single_select = None
            self._restore_hover_cursor(event.position().x(), event.position().y())
            self.update()
        super().mouseReleaseEvent(event)

    def _in_ltc_waveform(self, x: float, y: float) -> bool:
        if not self._ltc_lane_visible() or self._ltc_audio is None or x < self._header_width:
            return False
        top = self._ltc_lane_top_y()
        return top <= y < top + self._ltc_band_height()

    def _show_wave_gain_context_menu(self, pos) -> None:  # noqa: ANN001
        menu = QMenu(self)
        if self._show_wave_gain_line:
            toggle = menu.addAction("Hide volume adjustment")
        else:
            toggle = menu.addAction("Show volume adjustment")
        reset = None
        if self._show_wave_gain_line:
            menu.addSeparator()
            reset = menu.addAction("Reset to 0 dB")
        chosen = menu.exec(self.mapToGlobal(pos))
        if chosen is None:
            return
        if chosen is toggle:
            self.set_show_wave_gain_line(not self._show_wave_gain_line)
            self._invalidate_scrub_backdrop()
            self.update()
        elif reset is not None and chosen is reset and self._song is not None:
            self._song.audio_gain_db = 0.0
            self.audio_gain_changed.emit(0.0)
            self._sync_audio_gain_ui()
            self._invalidate_scrub_backdrop()
            self.update()

    def _show_ltc_gain_context_menu(self, pos) -> None:  # noqa: ANN001
        menu = QMenu(self)
        if self._show_ltc_gain_line:
            toggle = menu.addAction("Hide Music volume adjustment")
        else:
            toggle = menu.addAction("Show Music volume adjustment")
        reset = None
        if self._show_ltc_gain_line:
            menu.addSeparator()
            reset = menu.addAction("Reset Music to 0 dB")
        chosen = menu.exec(self.mapToGlobal(pos))
        if chosen is None:
            return
        if chosen is toggle:
            self.set_show_ltc_gain_line(not self._show_ltc_gain_line)
            self._invalidate_scrub_backdrop()
            self.update()
        elif reset is not None and chosen is reset and self._song is not None:
            self._song.music_volume = 1.0
            self._sync_music_volume_ui()
            self.music_volume_changed.emit(1.0)
            self._invalidate_scrub_backdrop()
            self.update()

    def _toggle_mark_lane_resize_bar(self) -> None:
        self._show_mark_lane_resize_bar = not self._show_mark_lane_resize_bar
        self._apply_layout_heights()
        self._invalidate_scrub_backdrop()
        self.update()

    def _show_mark_lane_context_menu(self, pos, lane_index: int) -> None:  # noqa: ANN001
        if self._song is None:
            return
        menu = QMenu(self)
        rename_act = menu.addAction("Rename…")
        menu.addSeparator()
        if self._show_mark_track_colors:
            color_act = menu.addAction("Hide track colors")
        else:
            color_act = menu.addAction("Show track colors")
        manager_act = menu.addAction("Mark Manager…")
        chosen = menu.exec(self.mapToGlobal(pos))
        if chosen is None:
            return
        if chosen is rename_act:
            self._rename_mark_lane_at(lane_index)
        elif chosen is color_act:
            self._set_mark_track_colors(not self._show_mark_track_colors)
        elif chosen is manager_act:
            self.mark_manager_requested.emit()

    def _set_mark_track_colors(self, show: bool) -> None:
        show = bool(show)
        if show == self._show_mark_track_colors:
            return
        self._show_mark_track_colors = show
        self._apply_layout_heights()
        self._invalidate_scrub_backdrop()
        self.update()
        self.mark_track_colors_changed.emit(show)

    def _show_mark_tracks_area_menu(self, pos) -> None:  # noqa: ANN001
        if self._song is None:
            return
        menu = QMenu(self)
        if self._show_mark_lane_resize_bar:
            resize = menu.addAction("Hide resize bar")
        else:
            resize = menu.addAction("Show resize bar")
        hidden = [lane for lane in self._song.mark_lanes if not lane.visible]
        show_actions: list[tuple[object, int]] = []
        if hidden:
            menu.addSeparator()
            for lane in sorted(hidden, key=lambda item: item.index):
                act = menu.addAction(f"Show “{lane.name}” track")
                show_actions.append((act, lane.index))
        chosen = menu.exec(self.mapToGlobal(pos))
        if chosen is None:
            return
        if chosen is resize:
            self._toggle_mark_lane_resize_bar()
            return
        for act, lane_index in show_actions:
            if chosen is act:
                self.set_lane_visible(lane_index, True)
                return

    def _show_context_menu(self, pos) -> None:  # noqa: ANN001
        if self._song is None:
            return
        x = float(pos.x())
        y = float(pos.y())
        lane_idx = self._lane_index_at(x, y)
        if lane_idx is not None and self._hit_mark_at(x, y) is None:
            self._show_mark_lane_context_menu(pos, lane_idx)
            return
        if x < self._header_width:
            return
        if self._in_video_lane(x, y):
            self._show_video_clip_context_menu(pos, x, y)
            return
        if self._in_waveform(x, y) and self._audio is not None:
            self._show_wave_gain_context_menu(pos)
            return
        if self._in_ltc_waveform(x, y):
            self._show_ltc_gain_context_menu(pos)
            return
        if self._in_mark_tracks(x, y) and self._hit_mark_at(x, y) is None:
            self._show_mark_tracks_area_menu(pos)
            return
        hit_id = self._hit_mark_at(x, y)
        if hit_id is not None and hit_id not in self._selected_mark_ids:
            self.set_selected_mark_ids([hit_id])
        ids = list(self._selected_mark_ids)
        menu = QMenu(self)
        if not ids:
            menu.addAction("(Select a Mark or right-click on one first)").setEnabled(False)
            menu.exec(self.mapToGlobal(pos))
            return

        n = len(ids)
        delete_action = menu.addAction(f"Delete Mark(s) ({n})")
        offset_action = menu.addAction("Offset Time…")
        menu.addSeparator()
        quick: list[tuple[object, float]] = []
        for label, delta in (
            ("+0.010s", 0.01),
            ("-0.010s", -0.01),
            ("+0.100s", 0.1),
            ("-0.100s", -0.1),
            ("+1.000s", 1.0),
            ("-1.000s", -1.0),
        ):
            act = menu.addAction(label)
            quick.append((act, delta))
        chosen = menu.exec(self.mapToGlobal(pos))
        if chosen is None:
            return
        if chosen is delete_action:
            self.delete_requested.emit(ids)
            return
        if chosen is offset_action:
            seconds, ok = QInputDialog.getDouble(
                self,
                "Offset Time",
                "Relative offset (seconds, negative allowed):",
                0.0,
                -3600.0,
                3600.0,
                3,
            )
            if ok and abs(seconds) >= 1e-6:
                self.offset_requested.emit(ids, float(seconds))
            return
        for act, delta in quick:
            if chosen is act:
                self.offset_requested.emit(ids, float(delta))
                return

    def wheelEvent(self, event) -> None:  # noqa: ANN001
        pixel = event.pixelDelta()
        angle = event.angleDelta()
        ctrl = bool(
            event.modifiers()
            & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.MetaModifier)
        )
        shift = bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)

        def _zoom(dy: float) -> None:
            self._release_view_pin(center_now=True)
            if dy > 0:
                self.zoom_by(1.12)
            elif dy < 0:
                self.zoom_by(1 / 1.12)

        def _pan(dx: float) -> None:
            self._view_pinned = True
            self._scroll_x -= dx * 0.9
            self._clamp_scroll()
            self._invalidate_scrub_backdrop()
            self.update()
            self.view_changed.emit()

        # Windows touchpads often only send angleDelta (same as a mouse wheel),
        # so also check device type / synthesized source / scroll phases.
        is_trackpad = bool(pixel.x() or pixel.y())
        try:
            device = event.device()
            if device is not None and device.type() == QInputDevice.DeviceType.TouchPad:
                is_trackpad = True
        except Exception:
            pass
        try:
            if event.source() == Qt.MouseEventSource.MouseEventSynthesizedBySystem:
                is_trackpad = True
        except Exception:
            pass
        try:
            if event.phase() != Qt.ScrollPhase.NoScrollPhase:
                is_trackpad = True
        except Exception:
            pass

        if pixel.x() or pixel.y():
            dx = float(pixel.x() if abs(pixel.x()) >= abs(pixel.y()) else pixel.y())
            dy = float(pixel.y() if pixel.y() else angle.y())
        else:
            dx = float(angle.x() if angle.x() else angle.y())
            dy = float(angle.y() if angle.y() else angle.x())

        if ctrl:
            _zoom(dy)
        elif shift:
            _pan(dx if dx else dy)
        elif is_trackpad:
            # Two-finger trackpad → pan view.
            _pan(dx if dx else dy)
        else:
            # Real mouse wheel → zoom.
            _zoom(dy)
        event.accept()

    def paintEvent(self, event) -> None:  # noqa: ANN001
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)

        # Scrub / play path: blit a cached static timeline and only redraw the
        # playhead so the UI never does full waveform+video paints on the clock
        # tick. Audio still advances on the PortAudio thread regardless.
        if self._can_use_static_backdrop():
            if self._blit_scrub_backdrop(painter):
                self._paint_marks_live(painter)
                self._paint_loop_region(painter)
                self._paint_playhead(painter)
                self._paint_audio_gain_overlays(painter)
                self._paint_drag_guides(painter)
                return

        painter.fillRect(self.rect(), QColor(BG_APP))
        self._paint_static_layers(painter)
        self._paint_marks_live(painter)
        self._paint_playhead(painter)
        self._paint_loop_region(painter)
        self._paint_audio_gain_overlays(painter)
        self._paint_drag_guides(painter)

    def _paint_selection_box(self, painter: QPainter) -> None:
        if not self._box_selecting:
            return
        rect = self._selection_box_rect()
        if rect.width() < 2 and rect.height() < 2:
            return
        # Same greyscale family as setlist / transport selection (theme ACCENT).
        fill = with_alpha(ACCENT, 40)
        border = with_alpha(ACCENT_HOVER, 220)
        painter.fillRect(rect, fill)
        painter.setPen(QPen(border, 1, Qt.PenStyle.DashLine))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(rect)

    def _paint_wave_splitter(self, painter: QPainter, wave_bottom: int) -> None:
        # Splitter bar between waveform and mark lanes (drag to resize).
        active = self._resizing_wave or self._wave_split_hover
        color = QColor("#5a5a5a") if active else QColor("#0d0d0d")
        right = self._paint_right()
        painter.fillRect(0, wave_bottom - 2, right, 4, color)
        if active:
            mid_x = self._header_width + (right - self._header_width) // 2
            painter.setPen(QPen(QColor("#a0a0a0"), 1))
            painter.drawLine(mid_x - 18, wave_bottom, mid_x + 18, wave_bottom)

    def _paint_video_lane_splitter(self, painter: QPainter) -> None:
        """Splitter at the bottom of the Video clip row (drag to resize waveforms)."""
        if not self._video_lane_visible():
            return
        bottom = self._video_lane_clip_bottom_y()
        active = self._resizing_video_lane or self._video_lane_split_hover
        color = QColor("#5a5a5a") if active else QColor("#0d0d0d")
        right = self._paint_right()
        painter.fillRect(0, bottom - 2, right, 4, color)
        if active:
            mid_x = self._header_width + (right - self._header_width) // 2
            painter.setPen(QPen(QColor("#a0a0a0"), 1))
            painter.drawLine(mid_x - 18, bottom, mid_x + 18, bottom)

    def _paint_video_lane(self, painter: QPainter) -> None:
        if not self._video_lane_visible():
            return
        top = self._video_lane_top_y()
        bottom = top + int(self._video_lane_height)
        height = bottom - top
        right = self._paint_right()
        painter.fillRect(self._header_width, top, right, height, QColor("#0c0c10"))
        painter.setPen(QColor("#27272a"))
        painter.drawLine(0, bottom - 1, right, bottom - 1)
        clip_row_height = min(height, int(self._video_lane_base_height))
        if self._video_track_expanded:
            divider_y = top + clip_row_height
            painter.drawLine(self._header_width, divider_y, right, divider_y)
        if self._song is None:
            return
        overlapping = self._song.overlapping_video_clip_ids()
        fm = painter.fontMetrics()
        for clip in self._song.video_clips:
            x0 = self._x_for_time(clip.start_seconds)
            x1 = self._x_for_time(clip.end_seconds)
            if x1 < self._header_width - 2 or x0 > right + 2:
                continue
            rx0 = max(x0, float(self._header_width))
            rx1 = min(x1, float(right))
            rect = QRectF(rx0, top + 3, max(2.0, rx1 - rx0), clip_row_height - 6)
            selected = clip.id in self._selected_clip_ids
            hovered = clip.id == self._hover_clip_id
            is_overlap = clip.id in overlapping
            if clip.hidden:
                base = QColor("#3f3f46")
            else:
                base = QColor("#3b5bdb")
            if selected:
                base = base.lighter(135)
            elif hovered:
                base = base.lighter(115)
            fill_alpha = 140 if clip.hidden else 200
            painter.fillRect(rect, with_alpha(base.name(), fill_alpha))
            if is_overlap and not clip.hidden:
                painter.fillRect(rect, with_alpha("#7c3aed", 45))
            self._paint_video_clip_waveform(painter, clip, rect)
            if is_overlap:
                border = QColor("#f4f4f5") if selected else QColor("#a78bfa")
                pen = QPen(border, 2 if selected else 1, Qt.PenStyle.DashLine)
            else:
                border = QColor("#f4f4f5") if selected else QColor("#18181b")
                pen = QPen(border, 2 if selected else 1)
            if clip.locked:
                pen.setStyle(Qt.PenStyle.DashLine)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(rect)
            label = clip.name + (" 🔒" if clip.locked else "")
            elided = fm.elidedText(label, Qt.TextElideMode.ElideRight, max(4, int(rect.width()) - 8))
            painter.setPen(QColor("#f4f4f5") if not clip.hidden else QColor("#a1a1aa"))
            painter.drawText(QPointF(rect.left() + 4, rect.top() + rect.height() / 2 + 4), elided)

    def _paint_video_clip_waveform(self, painter: QPainter, clip: VideoClip, rect: QRectF) -> None:
        if clip.hidden or clip.media_kind == "still":
            return
        # Always paint when peaks are cached. The play/scrub path rebuilds a
        # static backdrop that is reused for many frames — skipping here left
        # empty blue clip rects for the whole play session (waves only returned
        # on pause). Decode stays async via VideoClipWaveformCache.
        x_left = int(rect.left())
        x_right = int(rect.right())
        if x_right - x_left < 4:
            return

        duration = float(clip.duration_seconds)
        if duration <= 1e-9:
            return

        peaks = self._video_waveform_cache.peaks_for_paint(clip)
        if peaks is None or peaks.mono.size == 0:
            return

        mid = rect.center().y()
        amp = max(2.0, rect.height() / 2 - 3)
        color = QColor("#dbe4ff")
        color.setAlpha(70 if self._video_track_muted else 175)
        painter.setPen(QPen(color, 1))

        samples_per_pixel = peaks.sample_rate / max(1e-6, self._pixels_per_second)
        use_raw = samples_per_pixel <= 1.5

        try:
            for x in range(x_left, x_right):
                t0 = self._time_for_x(x)
                t1 = self._time_for_x(x + 1)
                clip_t0 = timeline_to_clip_local(t0, clip)
                clip_t1 = timeline_to_clip_local(t1, clip)
                if clip_t0 is None and clip_t1 is None:
                    continue
                if clip_t0 is None:
                    clip_t0 = 0.0
                if clip_t1 is None:
                    clip_t1 = duration
                clip_t0 = max(0.0, min(duration, clip_t0))
                clip_t1 = max(clip_t0, min(duration, clip_t1))
                if use_raw:
                    lo, hi = sample_source_raw_for_clip_times(
                        peaks, clip, clip_t0=clip_t0, clip_t1=clip_t1
                    )
                else:
                    lo, hi = sample_source_peaks_for_clip_times(
                        peaks,
                        clip,
                        clip_t0=clip_t0,
                        clip_t1=clip_t1,
                        samples_per_pixel=samples_per_pixel,
                    )
                painter.drawLine(QPointF(x, mid + lo * amp), QPointF(x, mid + hi * amp))
        except Exception:
            # Corrupt / partially-built peaks must never take down the UI.
            return

    def _paint_headers(self, painter: QPainter, wave_bottom: int, tracks_top: int) -> None:
        painter.save()
        painter.setClipRect(0, 0, self._header_width, self.height())
        text_w = max(24, self._header_width - 16)
        fm = painter.fontMetrics()
        if self._song is not None:
            num = format_setlist_number(self._song.setlist_number)
            label = f"{num}.{self._song.name}"
            base_font = painter.font()
            bold = QFont(base_font)
            bold.setWeight(QFont.Weight.Bold)
            painter.setFont(bold)
            painter.setPen(QColor("#e4e4e7"))
            header_h = max(20, wave_bottom - self._ruler_height - 8)
            painter.drawText(
                QRect(8, self._ruler_height + 4, text_w, header_h),
                int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                label,
            )
            painter.setFont(base_font)
        elif self._audio is not None:
            painter.setPen(QColor("#a1a1aa"))
            painter.drawText(8, self._ruler_height + 22, self._audio.path.name)
        if self._music_header_expanded:
            chrome_top = self._wave_bottom_y()
            chrome_h = int(self._music_chrome_extra())
            painter.fillRect(0, chrome_top, self._header_width, chrome_h, QColor("#111113"))
        if self._video_lane_visible():
            video_top = self._video_lane_top_y()
            video_h = int(self._video_lane_height)
            painter.fillRect(0, video_top, self._header_width, video_h, QColor("#111113"))
            row_h = int(self._video_lane_base_height)
            painter.setPen(QColor(COLOR_VIDEO))
            painter.drawText(8, video_top + int(row_h / 2) + 4, "Video")
            if self._video_track_expanded:
                clip = self._single_selected_video_clip()
                sub_top = video_top + row_h
                painter.setPen(QColor("#71717a"))
                name_text = (
                    fm.elidedText(clip.name, Qt.TextElideMode.ElideRight, text_w)
                    if clip is not None
                    else "No clip selected"
                )
                painter.drawText(8, sub_top + 13, name_text)
        if self._ltc_lane_visible():
            ltc_top = self._ltc_lane_top_y()
            ltc_h = self._ltc_band_height()
            painter.fillRect(0, ltc_top, self._header_width, ltc_h, QColor("#111113"))
            side = "L" if self._ltc_channel == 0 else "R" if self._ltc_channel == 1 else "?"
            painter.setPen(QColor(self._ltc_waveform_color))
            painter.drawText(8, ltc_top + int(ltc_h / 2) + 4, f"LTC {side}")
        self._paint_mark_track_headers(painter, tracks_top)
        painter.restore()

    def _paint_mark_track_headers(self, painter: QPainter, tracks_top: int) -> None:
        """Left-column Mark Type labels (hover + lane colors)."""
        if self._song is None or not self._show_mark_tracks:
            return
        text_w = max(24, self._header_width - 16)
        fm = painter.fontMetrics()
        y = tracks_top
        visible = [lane for lane in self._song.mark_lanes if lane.visible]
        for i, lane in enumerate(visible):
            hovered = lane.index == self._hover_mark_lane_header
            header_bg = QColor("#26262c") if hovered else QColor("#111113")
            painter.fillRect(0, y, self._header_width, self._lane_height, header_bg)
            self._paint_mark_lane_header_label(
                painter,
                lane,
                y=int(y),
                text_w=text_w,
                fm=fm,
            )
            y += self._lane_height
            gap = self._mark_lane_gap_px()
            if gap > 0 and i < len(visible) - 1:
                painter.fillRect(0, int(y), self._header_width, gap, QColor("#111113"))
                y += gap

    def _marks_overlay_bottom_y(self) -> int:
        if not self._show_mark_tracks or self._visible_lane_count() == 0:
            return self._tracks_top_y()
        bottom = self._mark_lane_split_y()
        if self._show_mark_lane_resize_bar:
            bottom += self._mark_lane_split_h
        return bottom

    def _paint_marks_live(self, painter: QPainter) -> None:
        """Repaint marks on top of the static backdrop (or full paint path).

        Marks are never baked into the play/scrub cache — rebuilding that cache
        on every shortcut mark was freezing playback on songs with many cues.
        """
        if self._song is None:
            return
        tracks_top = self._tracks_top_y()
        hw = int(self._header_width)
        w = int(self.width())

        if tracks_top > self._ruler_height:
            painter.save()
            painter.setClipRect(
                hw,
                self._ruler_height,
                max(0, w - hw),
                tracks_top - self._ruler_height,
            )
            self._paint_marks(
                painter,
                start_y=tracks_top,
                waveform_lines=True,
                lane_shapes=False,
            )
            painter.restore()

        if not self._show_mark_tracks:
            return
        bottom = self._marks_overlay_bottom_y()
        if bottom <= tracks_top:
            return
        band_h = bottom - tracks_top

        painter.save()
        painter.setClipRect(0, tracks_top, hw, band_h)
        painter.fillRect(0, tracks_top, hw, band_h, QColor("#111113"))
        self._paint_mark_track_headers(painter, tracks_top)
        painter.restore()

        painter.save()
        painter.setClipRect(hw, tracks_top, max(0, w - hw), band_h)
        self._paint_lanes(painter, start_y=tracks_top)
        self._paint_marks(
            painter,
            start_y=tracks_top,
            waveform_lines=False,
            lane_shapes=True,
        )
        painter.restore()

    def _paint_ruler(self, painter: QPainter) -> None:
        right = self._paint_right()
        painter.fillRect(self._header_width, 0, right, self._ruler_height, QColor("#09090b"))
        duration = self._duration()
        major, minor = self._ruler_steps()

        t0 = max(0.0, self._time_for_x(self._header_width) - major)
        t1 = min(duration, self._time_for_x(right) + major)

        # Minor ticks (no labels) for fine alignment when zoomed in.
        if minor > 0:
            painter.setPen(QColor("#27272a"))
            t = (t0 // minor) * minor
            while t <= t1 + 1e-12:
                # Skip positions that coincide with major ticks.
                if abs(round(t / major) * major - t) > minor * 0.01:
                    x = self._x_for_time(t)
                    if x >= self._header_width:
                        painter.drawLine(QPointF(x, self._ruler_height - 8), QPointF(x, self._ruler_height))
                t += minor

        painter.setPen(QColor("#a1a1aa"))
        t = (t0 // major) * major
        last_label_x = -1e9
        min_label_gap = 70.0
        while t <= t1 + 1e-12:
            x = self._x_for_time(t)
            if x >= self._header_width:
                painter.drawLine(QPointF(x, 0), QPointF(x, self._ruler_height))
                if x - last_label_x >= min_label_gap:
                    painter.drawText(int(x + 4), 18, self._format_ruler_time(t, major))
                    last_label_x = x
            t += major

    def _ruler_steps(self) -> tuple[float, float]:
        """Pick major/minor tick spacing so labels never crush together."""
        candidates = (
            0.001,
            0.002,
            0.005,
            0.01,
            0.02,
            0.05,
            0.1,
            0.2,
            0.5,
            1.0,
            2.0,
            5.0,
            10.0,
            15.0,
            30.0,
            60.0,
            120.0,
            300.0,
            600.0,
        )
        min_major_px = 78.0
        major = candidates[-1]
        for step in candidates:
            if step * self._pixels_per_second >= min_major_px:
                major = step
                break
        # Minor = 1/5 or 1/4 of major when there's room.
        if major >= 0.01 and (major / 5.0) * self._pixels_per_second >= 6.0:
            minor = major / 5.0
        elif major >= 0.002 and (major / 2.0) * self._pixels_per_second >= 6.0:
            minor = major / 2.0
        else:
            minor = 0.0
        return major, minor

    def _format_ruler_time(self, t: float, step: float) -> str:
        minutes = int(t // 60)
        seconds = t % 60
        if step < 0.01:
            return f"{minutes:02d}:{seconds:07.4f}"
        if step < 0.1:
            return f"{minutes:02d}:{seconds:06.3f}"
        if step < 1.0:
            return f"{minutes:02d}:{seconds:05.2f}"
        if step < 10.0:
            return f"{minutes:02d}:{seconds:04.1f}"
        return f"{minutes:02d}:{int(seconds):02d}"

    def _paint_waveform(self, painter: QPainter) -> int:
        y0 = self._ruler_height
        y1 = y0 + self._wave_height
        right = self._paint_right()
        painter.fillRect(self._header_width, y0, right, self._wave_height, QColor("#09090b"))

        if self._audio_loading:
            painter.setPen(QColor("#a1a1aa"))
            label = self._audio_loading_label
            line1 = "Loading waveform…"
            line2 = label if label else "Reading audio file"
            painter.drawText(self._header_width + 16, y0 + self._wave_height // 2 - 8, line1)
            painter.setPen(QColor("#71717a"))
            painter.drawText(self._header_width + 16, y0 + self._wave_height // 2 + 14, line2)
            painter.setPen(QColor("#27272a"))
            painter.drawLine(0, y1 - 1, right, y1 - 1)
            return y1

        if self._audio is None:
            painter.setPen(QColor("#71717a"))
            painter.drawText(
                self._header_width + 16,
                y0 + self._wave_height // 2,
                "Open audio to see a detailed waveform here (zoom in a lot to line up beats)",
            )
            painter.setPen(QColor("#27272a"))
            painter.drawLine(0, y1 - 1, right, y1 - 1)
            return y1

        mid = y0 + self._wave_height / 2
        amp = (self._wave_height / 2) - 8
        color = QColor(self._waveform_color or "#3dd68c")
        if not color.isValid():
            color = QColor("#3dd68c")
        painter.setPen(QPen(color, 1))

        view_left = self._header_width
        view_right = right
        samples_per_pixel = self._audio.sample_rate / self._pixels_per_second

        if samples_per_pixel <= 1.5:
            self._paint_waveform_raw(
                painter, self._audio, mid, amp, view_left, view_right
            )
        else:
            self._paint_waveform_peaks(
                painter,
                self._audio,
                mid,
                amp,
                view_left,
                view_right,
                samples_per_pixel,
            )

        painter.setPen(QColor("#27272a"))
        painter.drawLine(QPointF(self._header_width, mid), QPointF(right, mid))
        painter.drawLine(0, y1 - 1, right, y1 - 1)
        return y1

    def _paint_ltc_lane(self, painter: QPainter) -> None:
        if not self._ltc_lane_visible() or self._ltc_audio is None:
            return
        top = self._ltc_lane_top_y()
        height = self._ltc_band_height()
        right = self._paint_right()
        painter.fillRect(self._header_width, top, right, height, QColor("#0c0c0e"))
        painter.setPen(QColor("#27272a"))
        painter.drawLine(0, top + height - 1, right, top + height - 1)

        mid = top + height / 2
        amp = max(4.0, (height / 2) - 4)
        color = QColor(self._ltc_waveform_color)
        view_left = self._header_width
        view_right = right
        samples_per_pixel = self._ltc_audio.sample_rate / self._pixels_per_second
        # Reaper-style filled silhouette. Stroke-per-pixel peak lines make
        # bi-phase LTC look falsely "hairy" even when the stripe is clean —
        # that noise is rendering, not the file. Real dropouts still show as
        # thin / blank sections via the abs peak height.
        if samples_per_pixel <= 1.5:
            self._paint_ltc_silhouette_raw(
                painter, self._ltc_audio, mid, amp, view_left, view_right, color
            )
        else:
            self._paint_ltc_silhouette_peaks(
                painter,
                self._ltc_audio,
                mid,
                amp,
                view_left,
                view_right,
                samples_per_pixel,
                color,
            )
        painter.setPen(QColor("#3f3f46"))
        painter.drawLine(QPointF(self._header_width, mid), QPointF(right, mid))

    def _paint_ltc_silhouette_peaks(
        self,
        painter: QPainter,
        audio: AudioBuffer,
        mid: float,
        amp: float,
        view_left: int,
        view_right: int,
        samples_per_pixel: float,
        color: QColor,
    ) -> None:
        level = choose_peak_level(audio.peak_levels, samples_per_pixel)
        if level is None:
            return
        painter.setPen(Qt.PenStyle.NoPen)
        for x in range(view_left, view_right):
            t0 = self._time_for_x(x)
            t1 = self._time_for_x(x + 1)
            if t1 <= 0 or t0 >= self._duration():
                continue
            s0 = int(t0 * audio.sample_rate)
            s1 = int(t1 * audio.sample_rate)
            b0 = max(0, s0 // level.samples_per_bucket)
            b1 = min(level.maxs.size, max(b0 + 1, s1 // level.samples_per_bucket))
            lo = float(level.mins[b0:b1].min())
            hi = float(level.maxs[b0:b1].max())
            peak = max(abs(lo), abs(hi))
            if peak < 0.02:
                continue
            y0 = int(mid - peak * amp)
            y1 = int(mid + peak * amp)
            painter.fillRect(x, y0, 1, max(1, y1 - y0), color)

    def _paint_ltc_silhouette_raw(
        self,
        painter: QPainter,
        audio: AudioBuffer,
        mid: float,
        amp: float,
        view_left: int,
        view_right: int,
        color: QColor,
    ) -> None:
        mono = audio.mono
        sr = audio.sample_rate
        painter.setPen(Qt.PenStyle.NoPen)
        for x in range(view_left, view_right):
            t0 = self._time_for_x(x)
            t1 = self._time_for_x(x + 1)
            s0 = max(0, int(t0 * sr))
            s1 = min(mono.size, max(s0 + 1, int(t1 * sr)))
            if s0 >= mono.size:
                continue
            segment = mono[s0:s1]
            peak = float(np.max(np.abs(segment)))
            if peak < 0.02:
                continue
            y0 = int(mid - peak * amp)
            y1 = int(mid + peak * amp)
            painter.fillRect(x, y0, 1, max(1, y1 - y0), color)

    def _paint_waveform_peaks(
        self,
        painter: QPainter,
        audio: AudioBuffer,
        mid: float,
        amp: float,
        view_left: int,
        view_right: int,
        samples_per_pixel: float,
    ) -> None:
        level = choose_peak_level(audio.peak_levels, samples_per_pixel)
        if level is None:
            return
        for x in range(view_left, view_right):
            t0 = self._time_for_x(x)
            t1 = self._time_for_x(x + 1)
            if t1 <= 0 or t0 >= self._duration():
                continue
            s0 = int(t0 * audio.sample_rate)
            s1 = int(t1 * audio.sample_rate)
            b0 = max(0, s0 // level.samples_per_bucket)
            b1 = min(level.maxs.size, max(b0 + 1, s1 // level.samples_per_bucket))
            lo = float(level.mins[b0:b1].min())
            hi = float(level.maxs[b0:b1].max())
            painter.drawLine(QPointF(x, mid + lo * amp), QPointF(x, mid + hi * amp))

    def _paint_waveform_raw(
        self,
        painter: QPainter,
        audio: AudioBuffer,
        mid: float,
        amp: float,
        view_left: int,
        view_right: int,
    ) -> None:
        mono = audio.mono
        sr = audio.sample_rate
        for x in range(view_left, view_right):
            t0 = self._time_for_x(x)
            t1 = self._time_for_x(x + 1)
            s0 = max(0, int(t0 * sr))
            s1 = min(mono.size, max(s0 + 1, int(t1 * sr)))
            if s0 >= mono.size:
                continue
            segment = mono[s0:s1]
            lo = float(segment.min())
            hi = float(segment.max())
            painter.drawLine(QPointF(x, mid + lo * amp), QPointF(x, mid + hi * amp))

    def _paint_lanes(self, painter: QPainter, *, start_y: int) -> None:
        if self._song is None or not self._show_mark_tracks:
            return
        right = self._paint_right()
        if self._show_mark_track_colors:
            content_h = self._marks_content_height()
            if content_h <= 0:
                return
            painter.fillRect(self._header_width, start_y, right, content_h, QColor("#000000"))
            for lane_index, y0, y1 in self._lane_rects():
                lane = self._song.lane_by_index(lane_index)
                if lane is None:
                    continue
                painter.fillRect(
                    self._header_width,
                    int(y0),
                    right,
                    int(y1 - y0),
                    self._lane_row_fill(lane, header=False),
                )
            return

        divider = QColor("#27272a")
        for lane_index, y0, y1 in self._lane_rects():
            lane = self._song.lane_by_index(lane_index)
            if lane is None:
                continue
            bg = QColor("#141416") if lane.cue_id_enabled else QColor("#111113")
            painter.fillRect(self._header_width, int(y0), right, int(y1 - y0), bg)
            painter.setPen(divider)
            painter.drawLine(0, int(y1) - 1, right, int(y1) - 1)

    def _mark_overlay_pen(self, color: QColor) -> QPen:
        pen = QPen(color, max(1.0, self._mark_line_width))
        style = self._mark_line_style
        if style == "solid":
            pen.setStyle(Qt.PenStyle.SolidLine)
        elif style == "dot":
            pen.setStyle(Qt.PenStyle.CustomDashLine)
            pen.setDashPattern([1.5, max(1.0, self._mark_dash_off)])
        else:
            pen.setStyle(Qt.PenStyle.CustomDashLine)
            pen.setDashPattern([max(1.0, self._mark_dash_on), max(1.0, self._mark_dash_off)])
        return pen

    def _paint_marks(
        self,
        painter: QPainter,
        *,
        start_y: int,
        waveform_lines: bool = True,
        lane_shapes: bool = True,
    ) -> None:
        if self._song is None:
            return
        lane_y = {lane_index: y0 for lane_index, y0, _y1 in self._lane_rects()}
        right = self._paint_right()

        for mark in self._song.marks:
            lane = self._song.lane_by_index(mark.lane_index)
            if lane is not None and not lane.visible:
                continue
            color = QColor(lane.color if lane else "#ffffff")
            shape = lane.marker_shape if lane is not None else "circle"
            selected = mark.id in self._selected_mark_ids
            x = self._x_for_time(mark.time_seconds)
            if x < self._header_width - 2 or x > right + 2:
                continue
            # Waveform overlay line — use mark color (brighter when selected / dragging).
            dragging = self._dragging_marks and mark.id in self._drag_ids
            hovered = mark.id == self._hover_mark_id
            if waveform_lines:
                if hovered and not dragging:
                    # Soft white halo so you know which mark the cursor is on.
                    painter.setPen(QPen(QColor(255, 255, 255, 120), max(3.0, self._mark_line_width + 2.5)))
                    painter.drawLine(QPointF(x, self._ruler_height), QPointF(x, start_y))
                if dragging:
                    painter.setPen(QPen(color, max(2.0, self._mark_line_width + 1.5)))
                elif selected:
                    painter.setPen(QPen(color.lighter(130), max(2.0, self._mark_line_width + 1)))
                else:
                    painter.setPen(self._mark_overlay_pen(color))
                painter.drawLine(QPointF(x, self._ruler_height), QPointF(x, start_y))

            if not lane_shapes:
                continue
            y = lane_y.get(mark.lane_index)
            if y is None:
                continue
            if dragging:
                painter.fillRect(
                    int(x - 7),
                    int(y + 1),
                    14,
                    self._lane_height - 2,
                    QColor(color.red(), color.green(), color.blue(), 55),
                )
            if self._show_mark_stem:
                painter.setPen(QPen(color, 2.5 if (selected or dragging) else 2))
                painter.drawLine(QPointF(x, y + 3), QPointF(x, y + self._lane_height - 3))
            ring = selected or hovered or dragging
            draw_marker_shape(
                painter,
                x,
                y + self._lane_height / 2,
                color,
                shape,
                size=max(5.0, self._lane_height * (0.36 if (selected or dragging) else 0.28)),
                outline=QColor(255, 255, 255, 230 if selected else 210) if ring else None,
                outline_width=2.2 if selected else (2.0 if hovered or dragging else 1.8),
            )

    def _paint_drag_guides(self, painter: QPainter) -> None:
        """While dragging marks, draw guides + signed delta (how far you moved)."""
        if not self._dragging_marks or not self._drag_moved or self._song is None:
            return
        delta_label: str | None = None
        label_x = 0.0
        label_color = QColor("#ffffff")
        for mid in self._drag_ids:
            mark = self._song.mark_by_id(mid)
            if mark is None:
                continue
            lane = self._song.lane_by_index(mark.lane_index)
            color = QColor(lane.color if lane else "#ffffff")
            x = self._x_for_time(mark.time_seconds)
            if x < self._header_width - 2 or x > self.width() + 2:
                continue
            painter.setPen(QPen(color, 2))
            painter.drawLine(QPointF(x, 0), QPointF(x, self.height()))
            start_t = self._drag_start_times.get(mid)
            if delta_label is None and start_t is not None:
                dt = mark.time_seconds - start_t
                delta_label = f"{dt:+.3f}s"
                label_x = x
                label_color = color
        if delta_label is not None:
            painter.setPen(label_color)
            painter.drawText(int(label_x + 5), 14, delta_label)

    def _paint_loop_region(self, painter: QPainter) -> None:
        if self._loop_a is None and self._loop_b is None:
            return

        # Shaded span whenever both points exist (placement feedback), brighter
        # when Loop is armed. Previously the fill was nearly invisible (α≈28)
        # and easy to miss next to red cue marks.
        if (
            self._loop_a is not None
            and self._loop_b is not None
            and abs(self._loop_b - self._loop_a) >= 0.01
        ):
            a, b = sorted((self._loop_a, self._loop_b))
            x0 = max(self._header_width, self._x_for_time(a))
            x1 = min(self.width(), self._x_for_time(b))
            if x1 > x0:
                alpha = 56 if self._loop_enabled else 36
                tint = QColor(61, 214, 140, alpha)
                painter.fillRect(int(x0), 0, int(x1 - x0), self.height(), tint)

        for label, t, col in (
            ("A", self._loop_a, QColor("#3dd68c")),
            ("B", self._loop_b, QColor("#f0c14a")),
        ):
            if t is None:
                continue
            x = self._x_for_time(t)
            if x < self._header_width - 2 or x > self.width() + 2:
                continue
            handle = label.lower()
            thick = self._hover_loop == handle or self._dragging_loop == handle
            painter.setPen(QPen(col, 3 if thick else 2, Qt.PenStyle.SolidLine))
            painter.drawLine(QPointF(x, 0), QPointF(x, self.height()))
            # Flag label in the ruler band so it is not mistaken for a cue mark.
            flag_w, flag_h = 16, 14
            flag_rect = QRectF(x + 1, 2, flag_w, flag_h)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(col)
            painter.drawRoundedRect(flag_rect, 2, 2)
            painter.setPen(QColor("#0d0d0d"))
            font = painter.font()
            font.setBold(True)
            font.setPointSize(max(9, font.pointSize()))
            painter.setFont(font)
            painter.drawText(
                flag_rect,
                int(Qt.AlignmentFlag.AlignCenter),
                label,
            )
            if self._dragging_loop == handle:
                painter.setPen(col)
                painter.drawText(int(x + flag_w + 4), 14, f"{t:.3f}s")

    def _paint_playhead(self, painter: QPainter) -> None:
        x = self._x_for_time(self._position)
        if x < self._header_width or x > self.width():
            return
        color = QColor(self._playhead_color or "#ff5a5f")
        if not color.isValid():
            color = QColor("#ff5a5f")
        painter.setPen(QPen(color, 2))
        painter.drawLine(QPointF(x, 0), QPointF(x, self.height()))
