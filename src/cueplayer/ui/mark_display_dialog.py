"""Display settings: tracks, NOW lane assignment, waveform lines, sync offset."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from cueplayer.domain.models import Project, Song
from cueplayer.ui.mark_manager_dialog import ColorSwatchButton
from cueplayer.ui.spinboxes import NoWheelDoubleSpinBox, NoWheelSpinBox


class MarkDisplayDialog(QDialog):
    """Dedicated panel so the main transport stays clean."""

    settings_changed = Signal()
    calibrate_requested = Signal()

    def __init__(
        self,
        song: Song,
        *,
        project: Project | None = None,
        latency_ms: int = 0,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Display Settings")
        self.resize(520, 640)
        self._song = song
        self._project = project
        self._now_groups: dict[int, QButtonGroup] = {}

        layout = QVBoxLayout(self)
        hint = QLabel(
            "Keep waveform / audio / marks in sync: run \"Sync Calibration\" first, then fine-tune with the nudge buttons."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #8b949e;")
        layout.addWidget(hint)

        form = QFormLayout()
        form.setSpacing(10)

        self.tracks_box = QCheckBox("Show Mark Tracks below")
        self.tracks_box.setChecked(song.show_mark_tracks)
        form.addRow("Tracks", self.tracks_box)

        self.video_track_box = QCheckBox("Show Video / LTC Tracks")
        initial_video = (
            project.show_video_track if project is not None else song.show_video_track
        )
        self.video_track_box.setChecked(bool(initial_video))
        self.video_track_box.setToolTip(
            "Hide Video + LTC after alignment to free timeline space. "
            "Applies to the whole show (all songs). "
            "Preview / Clean Output keep playing either way. "
            "LTC lane appears under Video when a file stripe is known."
        )
        form.addRow("Video", self.video_track_box)

        self.stem_box = QCheckBox("Stem line through mark shapes")
        self.stem_box.setChecked(song.show_mark_stem)
        self.stem_box.setToolTip("Draws a vertical line above/below each Mark shape; turn off to show just the shape")
        form.addRow("Shape", self.stem_box)

        layout.addLayout(form)

        now_title = QLabel("NOW Display Assignment")
        now_title.setStyleSheet("font-weight: 600; color: #c5cddb; margin-top: 6px;")
        layout.addWidget(now_title)
        now_hint = QLabel(
            "Choose which tracks go to the primary display and which go to the secondary display. "
            "Each panel switches to the current Cue over time."
        )
        now_hint.setWordWrap(True)
        now_hint.setStyleSheet("color: #8b949e;")
        layout.addWidget(now_hint)

        self.secondary_enabled_box = QCheckBox("Enable secondary display")
        self.secondary_enabled_box.setChecked(song.now_secondary_enabled)
        self.secondary_enabled_box.setToolTip(
            "When off, the secondary display is hidden and its tracks merge into the primary display."
        )
        layout.addWidget(self.secondary_enabled_box)

        now_scroll = QScrollArea()
        now_scroll.setWidgetResizable(True)
        now_scroll.setMinimumHeight(160)
        now_scroll.setMaximumHeight(220)
        now_host = QWidget()
        self.now_list = QVBoxLayout(now_host)
        self.now_list.setSpacing(4)
        self.now_list.setContentsMargins(4, 4, 4, 4)
        self._build_now_lane_rows()
        self.now_list.addStretch(1)
        now_scroll.setWidget(now_host)
        layout.addWidget(now_scroll)

        clear_row = QHBoxLayout()
        self.secondary_clear_spin = NoWheelDoubleSpinBox()
        self.secondary_clear_spin.setRange(0.0, 30.0)
        self.secondary_clear_spin.setSingleStep(0.5)
        self.secondary_clear_spin.setDecimals(1)
        self.secondary_clear_spin.setSuffix(" s")
        self.secondary_clear_spin.setSpecialValueText("Never clear")
        self.secondary_clear_spin.setValue(float(song.now_secondary_clear_seconds))
        self.secondary_clear_spin.setToolTip(
            "Seconds before the secondary display (Button) auto-clears. 0 = stays forever."
        )
        clear_row.addWidget(self.secondary_clear_spin)
        clear_row.addStretch(1)
        clear_form = QFormLayout()
        clear_form.addRow("Secondary auto-clear", clear_row)
        layout.addLayout(clear_form)

        form2 = QFormLayout()
        form2.setSpacing(10)

        line_src = project if project is not None else song
        self.wave_color = ColorSwatchButton(line_src.waveform_color or "#3dd68c")
        self.wave_color.setToolTip("Audio waveform color — applies to the whole project")
        form2.addRow("Waveform Color (project)", self.wave_color)

        self.playhead_color = ColorSwatchButton(
            getattr(line_src, "playhead_color", None) or "#ff5a5f"
        )
        self.playhead_color.setToolTip("Playhead (NOW) line color — applies to the whole project")
        form2.addRow("Playhead Color (project)", self.playhead_color)

        self.line_style = QComboBox()
        self.line_style.addItem("Solid", "solid")
        self.line_style.addItem("Dashed", "dash")
        self.line_style.addItem("Dotted", "dot")
        idx = self.line_style.findData(line_src.mark_line_style)
        self.line_style.setCurrentIndex(idx if idx >= 0 else 0)
        self.line_style.setToolTip("Mark lines on the waveform — applies to the whole project")
        form2.addRow("Waveform Line Style (project)", self.line_style)

        self.line_width = NoWheelSpinBox()
        self.line_width.setRange(1, 12)
        self.line_width.setValue(int(round(line_src.mark_line_width)))
        self.line_width.setSuffix(" px")
        self.line_width.setToolTip("Applies to the whole project")
        form2.addRow("Waveform Line Width (project)", self.line_width)

        self.dash_spacing = NoWheelSpinBox()
        self.dash_spacing.setRange(1, 40)
        self.dash_spacing.setValue(int(round(line_src.mark_dash_on)))
        self.dash_spacing.setSuffix(" px")
        self.dash_spacing.setToolTip("Applies to the whole project (dashed / dotted only)")
        form2.addRow("Dash/Dot Spacing (project)", self.dash_spacing)

        sync_row = QHBoxLayout()
        self.latency_spin = NoWheelSpinBox()
        self.latency_spin.setRange(-200, 300)
        self.latency_spin.setValue(int(latency_ms))
        self.latency_spin.setSuffix(" ms")
        self.latency_spin.setToolTip(
            "Sync offset: red line/mark = write head − this value. Marked too early → decrease; too late → increase."
        )
        sync_row.addWidget(self.latency_spin)
        self.nudge_minus = QPushButton("−10")
        self.nudge_minus.setToolTip("Marks are too early: subtract 10ms")
        self.nudge_plus = QPushButton("+10")
        self.nudge_plus.setToolTip("Marks are too late: add 10ms")
        self.nudge_minus.setFixedWidth(44)
        self.nudge_plus.setFixedWidth(44)
        # Prevent Enter in spinboxes from also clicking these (Qt dialog autoDefault).
        for btn in (self.nudge_minus, self.nudge_plus):
            btn.setAutoDefault(False)
            btn.setDefault(False)
        sync_row.addWidget(self.nudge_minus)
        sync_row.addWidget(self.nudge_plus)
        form2.addRow("Sync Offset", sync_row)

        self.calibrate_btn = QPushButton("Sync Calibration… (mute the song · tap to a metronome)")
        self.calibrate_btn.setToolTip("Mutes the music and keeps only the BE; tap along at 60/100 BPM to measure this computer's latency")
        self.calibrate_btn.setAutoDefault(False)
        self.calibrate_btn.setDefault(False)
        form2.addRow("", self.calibrate_btn)

        layout.addLayout(form2)
        tip = QLabel(
            "Tip: marking on the waveform while paused needs no offset; marking during playback uses the sync offset. "
            "Calibrate once and it usually carries over for the same output device."
        )
        tip.setWordWrap(True)
        tip.setStyleSheet("color: #8b949e;")
        layout.addWidget(tip)
        layout.addStretch(1)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close_btn = buttons.button(QDialogButtonBox.StandardButton.Close)
        if close_btn is not None:
            close_btn.setAutoDefault(True)
            close_btn.setDefault(True)
            close_btn.clicked.connect(self.accept)
        layout.addWidget(buttons)

        self.tracks_box.toggled.connect(self._apply)
        self.video_track_box.toggled.connect(self._apply)
        self.stem_box.toggled.connect(self._apply)
        self.secondary_enabled_box.toggled.connect(self._on_secondary_enabled_toggled)
        self.secondary_clear_spin.valueChanged.connect(self._apply)
        self.wave_color.color_changed.connect(self._apply)
        self.playhead_color.color_changed.connect(self._apply)
        self.line_style.currentIndexChanged.connect(self._apply)
        self.line_width.valueChanged.connect(self._apply)
        self.dash_spacing.valueChanged.connect(self._apply)
        self.latency_spin.valueChanged.connect(self._apply)
        self.nudge_minus.clicked.connect(lambda: self._nudge(-10))
        self.nudge_plus.clicked.connect(lambda: self._nudge(10))
        self.calibrate_btn.clicked.connect(self.calibrate_requested.emit)
        self._sync_spacing_enabled()
        self._sync_secondary_ui()

    def _build_now_lane_rows(self) -> None:
        # Use stored assignment so disabling the secondary display doesn't rewrite radio state.
        primary, secondary = self._song.configured_now_groups()
        primary_set = set(primary)
        secondary_set = set(secondary)
        header = QLabel("Track                Off Screen    Primary    Secondary")
        header.setStyleSheet("color: #8b949e; font-size: 11px;")
        self.now_list.addWidget(header)

        for lane in sorted(self._song.mark_lanes, key=lambda item: item.index):
            row = QWidget()
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 2, 0, 2)
            name = QLabel(f"{lane.index}. {lane.name}")
            name.setStyleSheet(f"color: {lane.color}; min-width: 160px;")
            name.setToolTip(lane.name)

            group = QButtonGroup(row)
            none_btn = QRadioButton("Off")
            primary_btn = QRadioButton("Primary")
            secondary_btn = QRadioButton("Secondary")
            group.addButton(none_btn, 0)
            group.addButton(primary_btn, 1)
            group.addButton(secondary_btn, 2)
            if lane.index in primary_set:
                primary_btn.setChecked(True)
            elif lane.index in secondary_set:
                secondary_btn.setChecked(True)
            else:
                none_btn.setChecked(True)
            group.idClicked.connect(lambda _id: self._apply())
            self._now_groups[lane.index] = group

            row_layout.addWidget(name, stretch=1)
            row_layout.addWidget(none_btn)
            row_layout.addWidget(primary_btn)
            row_layout.addWidget(secondary_btn)
            self.now_list.addWidget(row)

    def _collect_now_lanes(self) -> tuple[list[int], list[int]]:
        primary: list[int] = []
        secondary: list[int] = []
        for index, group in sorted(self._now_groups.items()):
            role = group.checkedId()
            if role == 1:
                primary.append(index)
            elif role == 2:
                secondary.append(index)
        return primary, secondary

    def latency_ms(self) -> int:
        return int(self.latency_spin.value())

    def set_latency_ms(self, ms: int) -> None:
        self.latency_spin.blockSignals(True)
        self.latency_spin.setValue(int(ms))
        self.latency_spin.blockSignals(False)
        self._apply()

    def _nudge(self, delta: int) -> None:
        self.latency_spin.setValue(self.latency_spin.value() + delta)

    def _sync_spacing_enabled(self) -> None:
        style = str(self.line_style.currentData() or "dash")
        self.dash_spacing.setEnabled(style in ("dash", "dot"))

    def _sync_secondary_ui(self) -> None:
        enabled = self.secondary_enabled_box.isChecked()
        self.secondary_clear_spin.setEnabled(enabled)
        for group in self._now_groups.values():
            secondary_btn = group.button(2)
            if secondary_btn is not None:
                secondary_btn.setEnabled(enabled)

    def _on_secondary_enabled_toggled(self, _checked: bool) -> None:
        self._sync_secondary_ui()
        self._apply()

    def _apply(self) -> None:
        self._sync_spacing_enabled()
        self._song.show_mark_tracks = self.tracks_box.isChecked()
        show_video = self.video_track_box.isChecked()
        if self._project is not None:
            self._project.set_show_video_track(show_video)
        else:
            self._song.show_video_track = show_video
            self._song.show_ltc_track = show_video
        self._song.show_mark_stem = self.stem_box.isChecked()
        style = str(self.line_style.currentData() or "solid")
        if style not in ("solid", "dash", "dot"):
            style = "solid"
        spacing = float(self.dash_spacing.value())
        width = float(self.line_width.value())
        # Mark line look + waveform color are project-global (not per song).
        target = self._project if self._project is not None else self._song
        target.mark_line_style = style  # type: ignore[assignment]
        target.mark_line_width = width
        target.mark_dash_on = spacing
        target.mark_dash_off = spacing
        target.waveform_color = self.wave_color.color()
        if self._project is not None:
            self._project.playhead_color = self.playhead_color.color()
        elif hasattr(target, "playhead_color"):
            target.playhead_color = self.playhead_color.color()  # type: ignore[attr-defined]
        primary, secondary = self._collect_now_lanes()
        self._song.now_lanes_configured = True
        self._song.now_primary_lanes = primary
        self._song.now_secondary_lanes = secondary
        self._song.now_secondary_enabled = self.secondary_enabled_box.isChecked()
        self._song.now_secondary_clear_seconds = float(self.secondary_clear_spin.value())
        self.settings_changed.emit()
