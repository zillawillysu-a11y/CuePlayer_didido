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
    QWidget,
)

from cueplayer.ui.icon_button import IconButton
from cueplayer.ui.theme import SLIDER_QSS


def format_time(seconds: float) -> str:
    total_ms = int(round(seconds * 1000))
    mins, rem_ms = divmod(total_ms, 60_000)
    secs, ms = divmod(rem_ms, 1000)
    return f"{mins:02d}:{secs:02d}.{ms:03d}"


_TEXT_BTN = "QPushButton { height: 30px; padding: 0 10px; }"

_BIG_TEXT_BTN = "QPushButton { height: 48px; padding: 0 14px; font-size: 16px; font-weight: 600; }"


class TopToolBar(QWidget):
    """View-mode row (Timeline / Export) plus a hint label."""

    view_mode_changed = Signal(str)  # "timeline" | "ma_patch"

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(8)

        self.timeline_mode_button = QPushButton("Timeline")
        self.timeline_mode_button.setCheckable(True)
        self.timeline_mode_button.setChecked(True)
        self.timeline_mode_button.setToolTip("Marking / waveform timeline")
        self.patch_mode_button = QPushButton("Export")
        self.patch_mode_button.setCheckable(True)
        self.patch_mode_button.setToolTip("Show-wide Sequence / Fader patch and export")
        mode_group = QButtonGroup(self)
        mode_group.setExclusive(True)
        mode_group.addButton(self.timeline_mode_button)
        mode_group.addButton(self.patch_mode_button)

        self.hint_label = QLabel(
            "Top-left S = drag Mark · dashed box = box-select · A/B draggable anytime · Ctrl+Z"
        )
        self.hint_label.setStyleSheet("color: #8b949e;")

        for button in (
            self.timeline_mode_button,
            self.patch_mode_button,
        ):
            button.setFixedHeight(30)
            button.setStyleSheet(_TEXT_BTN)

        layout.addWidget(self.timeline_mode_button)
        layout.addWidget(self.patch_mode_button)
        layout.addStretch(1)
        layout.addWidget(self.hint_label)

        self.timeline_mode_button.toggled.connect(self._emit_mode)
        self.patch_mode_button.toggled.connect(self._emit_mode)

    def _emit_mode(self, checked: bool) -> None:
        if not checked:
            return
        if self.patch_mode_button.isChecked():
            self.view_mode_changed.emit("ma_patch")
        else:
            self.view_mode_changed.emit("timeline")

    def set_view_mode(self, mode: str) -> None:
        if mode == "ma_patch":
            self.patch_mode_button.setChecked(True)
        else:
            self.timeline_mode_button.setChecked(True)


class BottomTransportBar(QWidget):
    """Play / pause / stop + A-B loop, centered; volume on the right."""

    play_clicked = Signal()
    pause_clicked = Signal()
    stop_clicked = Signal()
    set_loop_a_clicked = Signal()
    set_loop_b_clicked = Signal()
    clear_loop_clicked = Signal()
    loop_toggled = Signal(bool)
    volume_changed = Signal(float)  # 0.0 … 1.0

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("bottomTransport")
        self.setStyleSheet(
            "#bottomTransport {"
            "  background: #09090b;"
            "  border-top: 1px solid #27272a;"
            "}"
        )
        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)

        big = QSize(56, 50)
        self.play_button = IconButton("play", "Play", size=big)
        self.pause_button = IconButton("pause", "Pause here", size=big)
        self.stop_button = IconButton("stop", "Stop and reset", size=big)

        self.loop_a_button = QPushButton("A")
        self.loop_a_button.setToolTip("Set point A")
        self.loop_b_button = QPushButton("B")
        self.loop_b_button.setToolTip("Set point B")
        self.loop_box = QCheckBox("Loop")
        self.loop_box.setToolTip("Loop playback between A and B")
        self.loop_box.setStyleSheet("QCheckBox { font-size: 15px; spacing: 8px; }")
        self.loop_clear_button = IconButton("clear", "Clear A / B", size=QSize(48, 50))
        self.loop_label = QLabel("AB —")
        self.loop_label.setStyleSheet("color: #8b949e; min-width: 200px; font-size: 14px;")

        self.time_label = QLabel("00:00.000 / 01:00.000")
        self.time_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.time_label.setStyleSheet(
            "color: #e6edf3; font-weight: 700; font-size: 20px; min-width: 220px;"
        )

        for button in (self.loop_a_button, self.loop_b_button):
            button.setFixedSize(48, 50)
            button.setStyleSheet(_BIG_TEXT_BTN)
            button.setAutoDefault(False)
            button.setDefault(False)

        self.volume_slider = QSlider(Qt.Orientation.Horizontal)
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setValue(100)
        self.volume_slider.setFixedWidth(140)
        self.volume_slider.setToolTip(
            "Master volume (music + video clip audio; never LTC)\n"
            "For Video/Music balance while aligning, use the Music fader in the expanded Video track chrome."
        )
        self.volume_slider.setStyleSheet(SLIDER_QSS)
        self.volume_value = QLabel("100%")
        self.volume_value.setFixedWidth(40)
        self.volume_value.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.volume_value.setStyleSheet("color: #a1a1aa; font-size: 12px;")

        self.tc_status = QLabel("")
        self.tc_status.setStyleSheet(
            "color: #a1a1aa; font-size: 12px; min-width: 72px;"
        )
        self.tc_status.setToolTip("Generated LTC / MTC status (Tools → Audio / Timecode)")
        self.tc_status.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        layout.addStretch(1)
        layout.addWidget(self.time_label)
        layout.addSpacing(20)
        layout.addWidget(self.play_button)
        layout.addWidget(self.pause_button)
        layout.addWidget(self.stop_button)
        layout.addSpacing(22)
        layout.addWidget(self.loop_a_button)
        layout.addWidget(self.loop_b_button)
        layout.addWidget(self.loop_box)
        layout.addWidget(self.loop_clear_button)
        layout.addWidget(self.loop_label)
        layout.addStretch(1)
        layout.addWidget(self.tc_status)
        layout.addSpacing(8)
        layout.addWidget(self.volume_slider)
        layout.addWidget(self.volume_value)

        self.play_button.clicked.connect(self.play_clicked.emit)
        self.pause_button.clicked.connect(self.pause_clicked.emit)
        self.stop_button.clicked.connect(self.stop_clicked.emit)
        self.loop_a_button.clicked.connect(self.set_loop_a_clicked.emit)
        self.loop_b_button.clicked.connect(self.set_loop_b_clicked.emit)
        self.loop_clear_button.clicked.connect(self.clear_loop_clicked.emit)
        self.loop_box.toggled.connect(self.loop_toggled.emit)
        self.volume_slider.valueChanged.connect(self._on_volume_slider)

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

    def set_timecode_status(self, *, ltc: bool, mtc: bool) -> None:
        parts: list[str] = []
        if ltc:
            parts.append("LTC")
        if mtc:
            parts.append("MTC")
        if parts:
            self.tc_status.setText(" · ".join(parts))
            self.tc_status.setStyleSheet(
                "color: #4a9eff; font-size: 12px; font-weight: 600; min-width: 72px;"
            )
        else:
            self.tc_status.setText("")
            self.tc_status.setStyleSheet(
                "color: #a1a1aa; font-size: 12px; min-width: 72px;"
            )


# Back-compat alias used by older imports / cue monitor time formatting.
TransportBar = BottomTransportBar
