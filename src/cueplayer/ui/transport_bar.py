"""Top toolbar + bottom-centered transport / A-B controls."""

from __future__ import annotations

from PySide6.QtCore import Qt, QSize, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from cueplayer.ui.icon_button import IconButton
from cueplayer.ui.theme import BG_APP, SLIDER_QSS, TEXT, TEXT_MUTED
from cueplayer.ui.timeline_overview import TimelineOverviewBar


def format_time(seconds: float) -> str:
    total_ms = int(round(seconds * 1000))
    mins, rem_ms = divmod(total_ms, 60_000)
    secs, ms = divmod(rem_ms, 1000)
    return f"{mins:02d}:{secs:02d}.{ms:03d}"


# Borderless text chips — glyph/label only, soft hover fill.
_FLAT_BTN = (
    "QPushButton {"
    "  background: transparent; border: none; border-radius: 6px;"
    "  color: #ededed; padding: 4px 10px;"
    "}"
    "QPushButton:hover { background: #222222; }"
    "QPushButton:pressed { background: #2a2a2a; }"
    "QPushButton:checked { background: #2a2a2a; color: #ffffff; }"
    "QPushButton:disabled { color: #555555; background: transparent; }"
)

_FLAT_BIG = (
    "QPushButton {"
    "  background: transparent; border: none; border-radius: 8px;"
    "  color: #ededed; font-size: 15px; font-weight: 600; padding: 6px 12px;"
    "}"
    "QPushButton:hover { background: #222222; }"
    "QPushButton:pressed { background: #2a2a2a; }"
    "QPushButton:disabled { color: #555555; background: transparent; }"
)


class TopToolBar(QWidget):
    """View-mode row (Timeline / Set List Sheet / Export)."""

    view_mode_changed = Signal(str)  # "timeline" | "setlist" | "ma_patch"

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(4)

        self.timeline_mode_button = QPushButton("Timeline")
        self.timeline_mode_button.setCheckable(True)
        self.timeline_mode_button.setChecked(True)
        self.timeline_mode_button.setToolTip("Marking / waveform timeline")
        self.setlist_mode_button = QPushButton("Set List Sheet")
        self.setlist_mode_button.setCheckable(True)
        self.setlist_mode_button.setToolTip(
            "Spreadsheet of song order, names, Timecode Generator starts, and notes"
        )
        self.patch_mode_button = QPushButton("Export")
        self.patch_mode_button.setCheckable(True)
        self.patch_mode_button.setToolTip("Show-wide Sequence / Fader patch and export")
        mode_group = QButtonGroup(self)
        mode_group.setExclusive(True)
        mode_group.addButton(self.timeline_mode_button)
        mode_group.addButton(self.setlist_mode_button)
        mode_group.addButton(self.patch_mode_button)

        for button in (
            self.timeline_mode_button,
            self.setlist_mode_button,
            self.patch_mode_button,
        ):
            button.setFixedHeight(30)
            button.setStyleSheet(_FLAT_BTN)
            button.setFlat(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)

        layout.addWidget(self.timeline_mode_button)
        layout.addWidget(self.setlist_mode_button)
        layout.addWidget(self.patch_mode_button)
        layout.addStretch(1)

        self.timeline_mode_button.toggled.connect(self._emit_mode)
        self.setlist_mode_button.toggled.connect(self._emit_mode)
        self.patch_mode_button.toggled.connect(self._emit_mode)

    def _emit_mode(self, checked: bool) -> None:
        if not checked:
            return
        if self.patch_mode_button.isChecked():
            self.view_mode_changed.emit("ma_patch")
        elif self.setlist_mode_button.isChecked():
            self.view_mode_changed.emit("setlist")
        else:
            self.view_mode_changed.emit("timeline")

    def set_view_mode(self, mode: str) -> None:
        if mode == "ma_patch":
            self.patch_mode_button.setChecked(True)
        elif mode == "setlist":
            self.setlist_mode_button.setChecked(True)
        else:
            self.timeline_mode_button.setChecked(True)


class BottomTransportBar(QWidget):
    """Full-width overview scrubber + Play / Pause / Stop + A-B loop."""

    play_clicked = Signal()
    pause_clicked = Signal()
    stop_clicked = Signal()
    set_loop_a_clicked = Signal()
    set_loop_b_clicked = Signal()
    clear_loop_clicked = Signal()
    loop_toggled = Signal(bool)
    volume_changed = Signal(float)  # 0.0 … 1.0
    seek_requested = Signal(float)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("bottomTransport")
        self.setStyleSheet(
            f"#bottomTransport {{"
            f"  background: {BG_APP};"
            f"  border-top: none;"
            "}"
        )
        root = QHBoxLayout(self)
        root.setContentsMargins(10, 4, 10, 8)
        root.setSpacing(8)

        # Center block: overview scrubber + transport / A-B (no big clock).
        center_host = QWidget()
        center_host.setMinimumWidth(360)
        center_host.setMaximumWidth(720)
        center = QVBoxLayout(center_host)
        center.setContentsMargins(0, 0, 0, 0)
        center.setSpacing(2)

        self.overview = TimelineOverviewBar()
        center.addWidget(self.overview)

        controls = QHBoxLayout()
        controls.setContentsMargins(4, 0, 4, 0)
        controls.setSpacing(8)

        big = QSize(52, 44)
        self.play_button = IconButton("play", "Play", size=big)
        self.pause_button = IconButton("pause", "Pause here", size=big)
        self.stop_button = IconButton("stop", "Stop and reset", size=big)

        self.loop_a_button = QPushButton("A")
        self.loop_a_button.setToolTip("Set point A")
        self.loop_b_button = QPushButton("B")
        self.loop_b_button.setToolTip("Set point B")
        self.loop_box = QCheckBox("Loop")
        self.loop_box.setToolTip("Loop playback between A and B")
        self.loop_box.setStyleSheet(
            f"QCheckBox {{ color: {TEXT}; font-size: 14px; spacing: 8px; border: none; }}"
        )
        self.loop_clear_button = IconButton("clear", "Clear A / B", size=QSize(44, 44))
        self.loop_label = QLabel("A —  B —")
        self.loop_label.setStyleSheet(f"color: {TEXT_MUTED}; min-width: 180px; font-size: 13px;")

        # Kept for set_times() callers; not shown (overview ends replace it).
        self.time_label = QLabel("")
        self.time_label.hide()

        for button in (self.loop_a_button, self.loop_b_button):
            button.setFixedSize(44, 44)
            button.setStyleSheet(_FLAT_BIG)
            button.setFlat(True)
            button.setAutoDefault(False)
            button.setDefault(False)
            button.setCursor(Qt.CursorShape.PointingHandCursor)

        controls.addStretch(1)
        controls.addWidget(self.play_button)
        controls.addWidget(self.pause_button)
        controls.addWidget(self.stop_button)
        controls.addSpacing(14)
        controls.addWidget(self.loop_a_button)
        controls.addWidget(self.loop_b_button)
        controls.addWidget(self.loop_box)
        controls.addWidget(self.loop_clear_button)
        controls.addWidget(self.loop_label)
        controls.addStretch(1)
        center.addLayout(controls)

        self.volume_slider = QSlider(Qt.Orientation.Horizontal)
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setValue(100)
        self.volume_slider.setFixedWidth(120)
        self.volume_slider.setToolTip(
            "Master volume (music + video clip audio; never LTC)\n"
            "For Video/Music balance while aligning, use the Music fader in the expanded Video track chrome."
        )
        self.volume_slider.setStyleSheet(SLIDER_QSS)
        self.volume_value = QLabel("100%")
        self.volume_value.setFixedWidth(40)
        self.volume_value.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.volume_value.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 12px;")

        self.tc_status = QLabel("")
        self.tc_status.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 12px; min-width: 72px;")
        self.tc_status.setToolTip("Generated LTC / MTC status (Tools → Audio / Midi / Timecode)")
        self.tc_status.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        # Matching left/right rails keep overview + transport optically centered.
        right = QHBoxLayout()
        right.setContentsMargins(0, 0, 0, 0)
        right.setSpacing(6)
        right.addStretch(1)
        right.addWidget(self.tc_status)
        right.addWidget(self.volume_slider)
        right.addWidget(self.volume_value)
        right_wrap = QWidget()
        right_wrap.setFixedWidth(240)
        right_wrap.setLayout(right)
        right_col = QVBoxLayout()
        right_col.setContentsMargins(0, 0, 0, 0)
        right_col.setSpacing(0)
        right_col.addStretch(1)
        right_col.addWidget(right_wrap)
        right_host = QWidget()
        right_host.setFixedWidth(240)
        right_host.setLayout(right_col)

        left_spacer = QWidget()
        left_spacer.setFixedWidth(240)

        root.addWidget(left_spacer)
        root.addStretch(1)
        root.addWidget(center_host, stretch=0)
        root.addStretch(1)
        root.addWidget(right_host)

        self.play_button.clicked.connect(self.play_clicked.emit)
        self.pause_button.clicked.connect(self.pause_clicked.emit)
        self.stop_button.clicked.connect(self.stop_clicked.emit)
        self.loop_a_button.clicked.connect(self.set_loop_a_clicked.emit)
        self.loop_b_button.clicked.connect(self.set_loop_b_clicked.emit)
        self.loop_clear_button.clicked.connect(self.clear_loop_clicked.emit)
        self.loop_box.toggled.connect(self.loop_toggled.emit)
        self.volume_slider.valueChanged.connect(self._on_volume_slider)
        self.overview.seek_requested.connect(self.seek_requested.emit)

    def _on_volume_slider(self, value: int) -> None:
        self.volume_value.setText(f"{int(value)}%")
        self.volume_changed.emit(value / 100.0)

    def set_volume(self, volume: float) -> None:
        """Set slider from 0.0…1.0 without re-emitting if unchanged."""
        pct = int(round(min(1.0, max(0.0, float(volume))) * 100))
        self.volume_slider.blockSignals(True)
        self.volume_slider.setValue(pct)
        self.volume_slider.blockSignals(False)
        self.volume_value.setText(f"{pct}%")

    def set_playing(self, playing: bool) -> None:
        self.play_button.setEnabled(not playing)
        self.pause_button.setEnabled(playing)
        self.play_button.set_active(False)
        self.pause_button.set_active(playing)

    def set_times(self, position: float, duration: float) -> None:
        text = f"{format_time(position)} / {format_time(duration)}"
        if text != self.time_label.text():
            self.time_label.setText(text)

    def set_overview_state(
        self,
        *,
        duration: float,
        position: float,
        view_start: float,
        view_end: float,
        title: str = "",
    ) -> None:
        if title:
            self.overview.set_title(title)
        self.overview.set_state(
            duration=duration,
            position=position,
            view_start=view_start,
            view_end=view_end,
        )

    def set_loop_status(
        self,
        a: float | None,
        b: float | None,
        *,
        enabled: bool,
    ) -> None:
        self.loop_box.blockSignals(True)
        self.loop_box.setChecked(enabled)
        self.loop_box.blockSignals(False)
        a_txt = format_time(a) if a is not None else "—"
        b_txt = format_time(b) if b is not None else "—"
        self.loop_label.setText(f"A {a_txt}  B {b_txt}")
        self.overview.set_loop(a, b)

    def set_timecode_status(self, *, ltc: bool, mtc: bool) -> None:
        parts: list[str] = []
        if ltc:
            parts.append("LTC")
        if mtc:
            parts.append("MTC")
        if parts:
            self.tc_status.setText(" · ".join(parts))
            self.tc_status.setStyleSheet(
                f"color: {TEXT_MUTED}; font-size: 12px; font-weight: 600; min-width: 72px;"
            )
        else:
            self.tc_status.setText("")
            self.tc_status.setStyleSheet(
                f"color: {TEXT_MUTED}; font-size: 12px; min-width: 72px;"
            )


# Back-compat alias used by older imports / cue monitor time formatting.
TransportBar = BottomTransportBar
