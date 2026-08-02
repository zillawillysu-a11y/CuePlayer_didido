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
    """Song clock: ``MM:SS.mmm``, or ``H:MM:SS.mmm`` when ≥ 1 hour."""
    total_ms = int(round(max(0.0, float(seconds)) * 1000.0))
    hours, rem_ms = divmod(total_ms, 3_600_000)
    mins, rem_ms = divmod(rem_ms, 60_000)
    secs, ms = divmod(rem_ms, 1000)
    if hours > 0:
        return f"{hours}:{mins:02d}:{secs:02d}.{ms:03d}"
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
    music_mute_toggled = Signal(bool)  # PC music mute (same as Web Remote Mute PC)
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

        self.music_mute_button = IconButton(
            "speaker_mute",
            "Mute PC music (LTC stays; same as Web Remote Mute PC)",
            size=QSize(36, 36),
            overlay=True,
        )
        self._music_muted = False

        self.volume_slider = QSlider(Qt.Orientation.Horizontal)
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setValue(100)
        self.volume_slider.setMinimumWidth(48)
        self.volume_slider.setMaximumWidth(120)
        self.volume_slider.setFixedWidth(120)
        self.volume_slider.setToolTip(
            "Master volume (music + video clip audio; never LTC)\n"
            "For Video/Music balance while aligning, expand the Music header chevron (next to the eye)."
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
        self._mute_btn_w = 36 + 6  # mute + gap before slider
        self._volume_rail_min = self._mute_btn_w + 48 + 6 + 40  # mute + slim slider + %
        self._volume_rail_pref = self._mute_btn_w + 120 + 6 + 40
        self._tc_rail_extra = 72 + 6

        self._center_anchor: QWidget | None = None

        # Balance spacer = A/B group width so Play/Pause/Stop sit on true center
        # while A/B remain immediately to the right of Stop.
        self._balance = QWidget()
        self._balance.setFixedWidth(0)

        self._ab_group = QWidget()
        ab_row = QHBoxLayout(self._ab_group)
        ab_row.setContentsMargins(0, 0, 0, 0)
        ab_row.setSpacing(8)
        self._ab_row = ab_row
        ab_row.addWidget(self.loop_a_button)
        ab_row.addWidget(self.loop_b_button)
        ab_row.addWidget(self.loop_button)
        ab_row.addWidget(self.loop_clear_button)
        self._transport_density = "full"  # full | compact | minimal
        self._row_layout = row
        self._cluster_gap = 14  # spacing between Stop and A/B group

        right = QHBoxLayout()
        right.setContentsMargins(0, 0, 0, 0)
        right.setSpacing(6)
        right.addStretch(1)
        right.addWidget(self.tc_status)
        right.addWidget(self.music_mute_button)
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
        self._cluster_gap_item = row.itemAt(row.count() - 1)
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
        self.music_mute_button.clicked.connect(self._on_music_mute_clicked)
        self.volume_slider.valueChanged.connect(self._on_volume_slider)
        self.overview.seek_requested.connect(self.seek_requested.emit)

    def minimumSizeHint(self) -> QSize:
        # Side rails use setFixedWidth for optical centering; that would otherwise
        # report ~1200px and freeze the main Setlist splitter on compact windows.
        height = super().minimumSizeHint().height()
        return QSize(320, height)

    def sizeHint(self) -> QSize:
        height = super().sizeHint().height()
        return QSize(max(480, self.width()), height)

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

    def _ab_width(self) -> int:
        self._ab_group.adjustSize()
        return max(1, self._ab_group.sizeHint().width())

    def _play_buttons_width(self) -> int:
        return (
            self.play_button.width()
            + self.pause_button.width()
            + self.stop_button.width()
        )

    def _row_spacing_total(self) -> int:
        """All QHBoxLayout spacings between the 10 row items (incl. stretches)."""
        spacing = int(self._row_layout.spacing()) if self._row_layout is not None else 8
        return 9 * spacing

    def _cluster_width(self) -> int:
        """Visible Play…Clear span (buttons + Stop→A gap + A/B group, no rails)."""
        gap = int(getattr(self, "_cluster_gap", 14))
        # Play/Pause/Stop contribute 2 of the 9 row spacings; counted in spacing total.
        return self._play_buttons_width() + gap + self._ab_width()

    def _centered_footprint(self, ab_w: int | None = None) -> int:
        """
        Non-stretch row width for optically-centered transport.

        `_balance` mirrors (gap + A/B) so Play/Pause/Stop sit on center while
        A/B stay to the right of Stop — that duplicate must be budgeted or the
        layout crushes A/B/Loop into each other on narrow windows.
        """
        gap = int(getattr(self, "_cluster_gap", 14))
        ab = self._ab_width() if ab_w is None else max(1, int(ab_w))
        return self._play_buttons_width() + 2 * (gap + ab) + self._row_spacing_total()

    def _apply_transport_density(self, density: str) -> None:
        """Shrink Play/A-B controls so the cluster fits on compact windows."""
        if density == getattr(self, "_transport_density", None):
            return
        self._transport_density = density
        if density == "full":
            play_sz, ab_sz, clear_sz = QSize(52, 44), QSize(44, 44), QSize(44, 44)
            loop_text, ab_spacing, gap = "Loop", 8, 14
            row_spacing = 8
        elif density == "compact":
            play_sz, ab_sz, clear_sz = QSize(44, 40), QSize(36, 40), QSize(36, 40)
            loop_text, ab_spacing, gap = "Loop", 4, 8
            row_spacing = 4
        else:
            play_sz, ab_sz, clear_sz = QSize(40, 36), QSize(32, 36), QSize(32, 36)
            loop_text, ab_spacing, gap = "L", 2, 4
            row_spacing = 2
        for btn in (self.play_button, self.pause_button, self.stop_button):
            btn.setFixedSize(play_sz)
        for btn in (self.loop_a_button, self.loop_b_button):
            btn.setFixedSize(ab_sz)
        self.loop_clear_button.setFixedSize(clear_sz)
        self.loop_button.setText(loop_text)
        self.loop_button.setFixedHeight(ab_sz.height())
        if density == "minimal":
            self.loop_button.setFixedWidth(max(28, ab_sz.width() + 4))
        else:
            # Undo any prior setFixedWidth from minimal mode.
            self.loop_button.setMinimumWidth(0)
            self.loop_button.setMaximumWidth(16777215)
        self._ab_row.setSpacing(ab_spacing)
        if getattr(self, "_row_layout", None) is not None:
            self._row_layout.setSpacing(row_spacing)
        self._cluster_gap = gap
        gap_item = getattr(self, "_cluster_gap_item", None)
        if gap_item is not None and gap_item.spacerItem() is not None:
            gap_item.spacerItem().changeSize(gap, 0)
        self._ab_group.adjustSize()

    def _pick_transport_density(self) -> str:
        """Choose the densest control size that still fits centered Play…Clear + volume."""
        width = max(0, self.width())
        margins = 20
        # Try fullest first. Budget includes the optical-centering balance spacer.
        for density, vol_floor in (
            ("full", self._volume_rail_min),
            ("compact", self._volume_rail_min),
            ("minimal", 0),
        ):
            self._apply_transport_density(density)
            need = margins + self._centered_footprint() + vol_floor
            if need <= width:
                return density
        self._apply_transport_density("minimal")
        return "minimal"

    def _sync_transport_geometry(self) -> None:
        """Center overview track under anchor; align track (no time gutters) to Play…X."""
        self._pick_transport_density()
        ab_w = self._ab_width()
        # Keep A/B/Loop/Clear from being crushed when the row runs out of space.
        if self._ab_group.minimumWidth() != ab_w:
            self._ab_group.setMinimumWidth(ab_w)
        gap = int(getattr(self, "_cluster_gap", 14))
        ideal_trail = gap + ab_w
        margins = 20
        spacing_budget = self._row_spacing_total()
        play_w = self._play_buttons_width()
        # Prefer full optical centering; shrink balance before crushing controls.
        vol_reserve = self._volume_rail_min
        room_for_trail = max(
            0,
            self.width()
            - margins
            - play_w
            - gap
            - ab_w
            - spacing_budget
            - vol_reserve,
        )
        # If even volume floor does not fit, drop volume reserve and shrink trail.
        if (
            room_for_trail == 0
            and self.width() - margins - play_w - gap - ab_w - spacing_budget
            < vol_reserve
        ):
            vol_reserve = 0
            room_for_trail = max(
                0,
                self.width() - margins - play_w - gap - ab_w - spacing_budget,
            )
        trail = min(ideal_trail, room_for_trail)
        if self._balance.width() != trail:
            self._balance.setFixedWidth(trail)

        footprint = play_w + gap + ab_w + trail + spacing_budget
        max_pair = max(0, self.width() - margins - footprint)

        # Right rail must keep the master volume visible on compact windows.
        # Prefer: hide LTC/MTC chip → shrink slider → steal from left rail.
        # In minimal density, volume may yield entirely if cluster still barely fits.
        has_tc = bool(self.tc_status.text().strip())
        vol_pref = self._volume_rail_pref + (self._tc_rail_extra if has_tc else 0)
        vol_min = (
            0
            if (
                self._transport_density == "minimal"
                and max_pair < self._volume_rail_min
            )
            or vol_reserve == 0
            else self._volume_rail_min
        )
        show_volume = max_pair >= max(40, vol_min) if vol_min else max_pair >= 40
        if self.volume_slider.isVisible() != show_volume:
            self.volume_slider.setVisible(show_volume)
            self.volume_value.setVisible(show_volume)
        if self.music_mute_button.isVisible() != show_volume:
            self.music_mute_button.setVisible(show_volume)
        if not show_volume:
            vol_min = 0

        right_budget = max(vol_min, min(vol_pref, max_pair)) if show_volume else 0
        # Hide TC chip when it would push volume off-screen.
        show_tc = (
            has_tc
            and show_volume
            and right_budget >= self._volume_rail_pref + self._tc_rail_extra
        )
        if self.tc_status.isVisible() != show_tc:
            self.tc_status.setVisible(show_tc)
        if show_volume:
            slider_w = 120
            mute_gap = int(getattr(self, "_mute_btn_w", 42))
            if right_budget < self._volume_rail_pref:
                slider_w = max(48, right_budget - mute_gap - 6 - 40)
            if self.volume_slider.width() != slider_w:
                self.volume_slider.setFixedWidth(slider_w)

        self._right_rail.adjustSize()
        if show_volume:
            base_rail = max(
                vol_min,
                min(max(0, self._right_rail.sizeHint().width()), max_pair // 2),
            )
            if max_pair >= vol_min:
                base_rail = max(base_rail, min(vol_min, max_pair))
        else:
            base_rail = 0

        anchor_c = self._anchor_center_x(self._center_anchor)

        # Measure where the Play…Clear span sits with symmetric side rails.
        if self._left_rail.width() != base_rail:
            self._left_rail.setFixedWidth(base_rail)
        if self._right_rail.width() != base_rail:
            self._right_rail.setFixedWidth(base_rail)
        lay = self.layout()
        if lay is not None:
            lay.activate()

        play_l = self.play_button.mapTo(self, self.play_button.rect().topLeft()).x()
        clear_r = self.loop_clear_button.mapTo(
            self, self.loop_clear_button.rect().topRight()
        ).x()
        cluster_bias = (play_l + clear_r) / 2.0 - self.width() / 2.0

        delta = 0
        if anchor_c is not None:
            delta = int(round(anchor_c - self.width() / 2.0 - cluster_bias))
        left_w = max(0, base_rail + delta)
        right_w = max(0, base_rail - delta)
        # Keep total rail budget inside the bar after anchor shift.
        if left_w + right_w > max_pair:
            overflow = left_w + right_w - max_pair
            if delta >= 0:
                left_w = max(0, left_w - overflow)
            else:
                right_w = max(0, right_w - overflow)
        # Guarantee volume rail: steal from left spacer if needed.
        if show_volume and max_pair >= vol_min and right_w < vol_min:
            need = vol_min - right_w
            take = min(need, left_w)
            left_w -= take
            right_w += take
            if right_w < vol_min and max_pair >= vol_min:
                right_w = min(vol_min, max_pair)
                left_w = max(0, max_pair - right_w)
        if self._left_rail.width() != left_w:
            self._left_rail.setFixedWidth(left_w)
        if self._right_rail.width() != right_w:
            self._right_rail.setFixedWidth(right_w)
        if lay is not None:
            lay.activate()

        if anchor_c is not None:
            play_l = self.play_button.mapTo(self, self.play_button.rect().topLeft()).x()
            clear_r = self.loop_clear_button.mapTo(
                self, self.loop_clear_button.rect().topRight()
            ).x()
            err = anchor_c - (play_l + clear_r) / 2.0
            if abs(err) >= 1.0:
                delta2 = int(round(err))
                left_w = max(0, left_w + delta2)
                right_w = max(0, right_w - delta2)
                if left_w + right_w > max_pair:
                    overflow = left_w + right_w - max_pair
                    if delta2 >= 0:
                        left_w = max(0, left_w - overflow)
                    else:
                        right_w = max(0, right_w - overflow)
                if show_volume and max_pair >= vol_min and right_w < vol_min:
                    need = vol_min - right_w
                    take = min(need, left_w)
                    left_w -= take
                    right_w += take
                if self._left_rail.width() != left_w:
                    self._left_rail.setFixedWidth(left_w)
                if self._right_rail.width() != right_w:
                    self._right_rail.setFixedWidth(right_w)
                lay.activate()

        # Final guard: never let the volume rail paint over A/B/Loop/Clear.
        if show_volume and lay is not None:
            clear_r = self.loop_clear_button.mapTo(
                self, self.loop_clear_button.rect().topRight()
            ).x()
            rail_l = self._right_rail.mapTo(self, self._right_rail.rect().topLeft()).x()
            if rail_l < clear_r - 1:
                overflow = clear_r - rail_l
                right_w = max(0, right_w - overflow)
                left_w = max(0, max_pair - right_w)
                if right_w < max(40, vol_min if vol_min else 40):
                    right_w = 0
                    left_w = 0
                    if self.volume_slider.isVisible():
                        self.volume_slider.setVisible(False)
                        self.volume_value.setVisible(False)
                    if self.music_mute_button.isVisible():
                        self.music_mute_button.setVisible(False)
                if self._left_rail.width() != left_w:
                    self._left_rail.setFixedWidth(left_w)
                if self._right_rail.width() != right_w:
                    self._right_rail.setFixedWidth(right_w)
                lay.activate()

        # mapTo requires an ancestor — project through this widget.
        play_l = self.play_button.mapTo(self, self.play_button.rect().topLeft()).x()
        clear_r = self.loop_clear_button.mapTo(
            self, self.loop_clear_button.rect().topRight()
        ).x()
        host_l = self._overview_host.mapTo(self, self._overview_host.rect().topLeft()).x()
        host_w = max(1, self._overview_host.width())
        track_w = max(40, int(clear_r - play_l))
        # Shrink time gutters on a short overview so end times are not clipped.
        gutter = min(
            int(TimelineOverviewBar._LABEL_GUTTER),
            max(24, (host_w - track_w) // 2),
        )
        ov_w = track_w + 2 * gutter
        ov_x = int(play_l - gutter - host_l)
        # Keep the overview fully inside the host (no left/right crop).
        if ov_x < 0:
            ov_w += ov_x
            ov_x = 0
        if ov_x + ov_w > host_w:
            ov_w = max(40, host_w - ov_x)
        # After clamping, gutters must still fit inside the widget width.
        gutter = min(gutter, max(24, (ov_w - 40) // 2))
        self.overview.setGeometry(ov_x, 0, ov_w, self._overview_host.height())
        self.overview.set_label_gutter(gutter)

    def _anchor_center_x(self, widget: QWidget | None) -> float | None:
        if widget is None or widget.width() < 8:
            return None
        if not widget.isVisibleTo(self):
            return None
        anchor_point = None
        anchor_fn = getattr(widget, "transport_anchor_global_point", None)
        if callable(anchor_fn):
            anchor_point = anchor_fn()
        if anchor_point is None:
            anchor_point = widget.mapToGlobal(widget.rect().center())
        return float(self.mapFromGlobal(anchor_point).x())

    def _on_volume_slider(self, value: int) -> None:
        self.volume_value.setText(f"{int(value)}%")
        self.volume_changed.emit(value / 100.0)

    def _on_music_mute_clicked(self) -> None:
        muted = not self._music_muted
        self.set_music_muted(muted)
        self.music_mute_toggled.emit(muted)

    def set_music_muted(self, muted: bool) -> None:
        """Sync mute chip from engine / Web Remote (does not re-emit)."""
        self._music_muted = bool(muted)
        self.music_mute_button.set_active(self._music_muted)
        self.music_mute_button.setToolTip(
            "Unmute PC music (LTC never muted; same as Web Remote Mute PC)"
            if self._music_muted
            else "Mute PC music (LTC stays; same as Web Remote Mute PC)"
        )

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
