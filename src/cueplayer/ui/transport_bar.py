"""Top toolbar + bottom-centered transport / A-B controls."""

from __future__ import annotations

from PySide6.QtCore import Qt, QSize, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from cueplayer.ui.icon_button import IconButton
from cueplayer.ui.theme import BG_APP, SLIDER_QSS, TEXT_MUTED
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

# Light chip when on — matches timeline Auto Scroll overlay toggles.
_CHIP_TOGGLE = (
    "QPushButton {"
    "  background: rgba(24, 24, 24, 140); border: none; border-radius: 6px;"
    "  color: #ededed; font-size: 14px; font-weight: 600; padding: 6px 12px;"
    "}"
    "QPushButton:hover { background: rgba(48, 48, 48, 200); }"
    "QPushButton:pressed { background: rgba(40, 40, 40, 220); }"
    "QPushButton:checked {"
    "  background: rgba(232, 232, 232, 235); color: #111111;"
    "}"
    "QPushButton:checked:hover { background: rgba(245, 245, 245, 245); }"
    "QPushButton:checked:pressed { background: rgba(200, 200, 200, 245); }"
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
    """Overview scrubber + centered Play/Pause/Stop + A-B to the right of Stop."""

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
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 4, 10, 8)
        root.setSpacing(2)

        # Overview host — child is positioned so the *track* (not time gutters)
        # spans Play…Clear (X).
        self._overview_host = QWidget()
        self._overview_host.setFixedHeight(26)
        self.overview = TimelineOverviewBar(self._overview_host)
        self.overview.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        root.addWidget(self._overview_host)

        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)

        big = QSize(52, 44)
        self.play_button = IconButton("play", "Play", size=big)
        self.pause_button = IconButton("pause", "Pause here", size=big)
        self.stop_button = IconButton("stop", "Stop and reset", size=big)

        self.loop_a_button = QPushButton("A")
        self.loop_a_button.setToolTip("Set point A")
        self.loop_b_button = QPushButton("B")
        self.loop_b_button.setToolTip("Set point B")
        self.loop_button = QPushButton("Loop")
        self.loop_button.setCheckable(True)
        self.loop_button.setToolTip("Loop playback between A and B (on when highlighted)")
        self.loop_button.setStyleSheet(_CHIP_TOGGLE)
        self.loop_button.setFlat(True)
        self.loop_button.setAutoDefault(False)
        self.loop_button.setDefault(False)
        self.loop_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.loop_button.setFixedHeight(44)
        self.loop_clear_button = IconButton("clear", "Clear A / B", size=QSize(44, 44))

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

        self._center_anchor: QWidget | None = None

        # Balance spacer = A/B group width so Play/Pause/Stop sit on true center
        # while A/B remain immediately to the right of Stop.
        self._balance = QWidget()
        self._balance.setFixedWidth(0)

        self._ab_group = QWidget()
        ab_row = QHBoxLayout(self._ab_group)
        ab_row.setContentsMargins(0, 0, 0, 0)
        ab_row.setSpacing(8)
        ab_row.addWidget(self.loop_a_button)
        ab_row.addWidget(self.loop_b_button)
        ab_row.addWidget(self.loop_button)
        ab_row.addWidget(self.loop_clear_button)

        right = QHBoxLayout()
        right.setContentsMargins(0, 0, 0, 0)
        right.setSpacing(6)
        right.addStretch(1)
        right.addWidget(self.tc_status)
        right.addWidget(self.volume_slider)
        right.addWidget(self.volume_value)
        right_host = QWidget()
        right_host.setLayout(right)
        self._right_rail = right_host

        left_spacer = QWidget()
        self._left_rail = left_spacer

        row.addWidget(self._left_rail)
        row.addStretch(1)
        row.addWidget(self._balance)
        row.addWidget(self.play_button)
        row.addWidget(self.pause_button)
        row.addWidget(self.stop_button)
        row.addSpacing(14)
        row.addWidget(self._ab_group)
        row.addStretch(1)
        row.addWidget(self._right_rail)
        root.addLayout(row)

        self.play_button.clicked.connect(self.play_clicked.emit)
        self.pause_button.clicked.connect(self.pause_clicked.emit)
        self.stop_button.clicked.connect(self.stop_clicked.emit)
        self.loop_a_button.clicked.connect(self.set_loop_a_clicked.emit)
        self.loop_b_button.clicked.connect(self.set_loop_b_clicked.emit)
        self.loop_clear_button.clicked.connect(self.clear_loop_clicked.emit)
        self.loop_button.toggled.connect(self.loop_toggled.emit)
        self.volume_slider.valueChanged.connect(self._on_volume_slider)
        self.overview.seek_requested.connect(self.seek_requested.emit)

    def set_center_anchor(self, widget: QWidget | None) -> None:
        """Optically center transport under this widget (e.g. timeline column)."""
        self._center_anchor = widget
        self.sync_geometry()

    def sync_geometry(self) -> None:
        self._sync_transport_geometry()

    def showEvent(self, event) -> None:  # noqa: ANN001
        super().showEvent(event)
        self._sync_transport_geometry()

    def resizeEvent(self, event) -> None:  # noqa: ANN001
        super().resizeEvent(event)
        self._sync_transport_geometry()

    def _sync_transport_geometry(self) -> None:
        """Center Play/Pause/Stop; align overview *track* (no time gutters) to Play…X."""
        self._ab_group.adjustSize()
        self._right_rail.adjustSize()
        ab_w = max(0, self._ab_group.sizeHint().width())
        # Pad left of Play by everything that sits to the right of Stop before
        # the trailing stretch (spacing + A/B group).
        trail = 14 + ab_w
        if self._balance.width() != trail:
            self._balance.setFixedWidth(trail)

        base_rail = max(0, self._right_rail.sizeHint().width())
        delta = 0
        anchor = self._center_anchor
        if anchor is not None and anchor.isVisible() and anchor.width() >= 8:
            anchor_c = anchor.mapTo(self, anchor.rect().center()).x()
            delta = int(round(anchor_c - self.width() / 2.0))
        left_w = max(0, base_rail + delta)
        right_w = max(0, base_rail - delta)
        if self._left_rail.width() != left_w:
            self._left_rail.setFixedWidth(left_w)
        if self._right_rail.width() != right_w:
            self._right_rail.setFixedWidth(right_w)

        lay = self.layout()
        if lay is not None:
            lay.activate()

        # mapTo requires an ancestor — project through this widget.
        play_l = self.play_button.mapTo(self, self.play_button.rect().topLeft()).x()
        clear_r = self.loop_clear_button.mapTo(
            self, self.loop_clear_button.rect().topRight()
        ).x()
        host_l = self._overview_host.mapTo(self, self._overview_host.rect().topLeft()).x()
        gutter = int(TimelineOverviewBar._LABEL_GUTTER)
        # Widget is wider than the track by gutters on each side; times sit outside
        # the Play…X span, while the hairline track matches that span.
        track_w = max(80, int(clear_r - play_l))
        ov_w = track_w + 2 * gutter
        ov_x = int(play_l - gutter - host_l)
        self.overview.setGeometry(ov_x, 0, ov_w, self._overview_host.height())

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
        self.loop_button.blockSignals(True)
        self.loop_button.setChecked(enabled)
        self.loop_button.blockSignals(False)
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
        self.sync_geometry()


# Back-compat alias used by older imports / cue monitor time formatting.
TransportBar = BottomTransportBar
