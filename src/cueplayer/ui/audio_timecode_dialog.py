"""Audio output device, channel routing, and LTC / MTC settings dialog."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from cueplayer.domain.models import (
    AudioOutputSettings,
    clamp_output_channels,
    default_channel_routing,
    default_ltc_channels_for_device,
)
from cueplayer.playback.devices import find_output_device, list_output_devices
from cueplayer.playback.mtc_output import list_midi_output_names
from cueplayer.ui.spinboxes import NoWheelComboBox
from cueplayer.ui.theme import SLIDER_QSS


def _channels_to_ui(channels: list[int]) -> str:
    """0-based list → human '1+2' style string."""
    if not channels:
        return ""
    return "+".join(str(int(c) + 1) for c in channels)


def _parse_channel_ui(text: str, *, max_ch: int) -> list[int] | None:
    """
    Parse '1', '1+2', '3', '1,2' (1-based) → 0-based indices.
    Empty string → []. None on parse error.
    Values above ``max_ch`` are clamped into range (e.g. LTC 3 → 2 on stereo).
    """
    raw = text.strip().replace(",", "+").replace(" ", "")
    if not raw:
        return []
    parts = [p for p in raw.split("+") if p]
    out: list[int] = []
    for part in parts:
        try:
            one_based = int(part)
        except ValueError:
            return None
        if one_based < 1:
            return None
        idx = one_based - 1
        if max_ch > 0 and idx >= max_ch:
            idx = max_ch - 1
        if idx not in out:
            out.append(idx)
    return out


def _clamp_channel_ui_text(
    text: str, *, max_ch: int, fallback: list[int] | None = None
) -> str:
    """Clamp a 1-based channel field into 1..max_ch; use fallback if empty/invalid."""
    parsed = _parse_channel_ui(text, max_ch=max_ch)
    if parsed is None:
        parsed = []
    if not parsed and fallback is not None:
        parsed = clamp_output_channels(list(fallback), max_ch)
    return _channels_to_ui(parsed)


class AudioTimecodeDialog(QDialog):
    """Tools → Audio / Timecode…"""

    def __init__(
        self,
        settings: AudioOutputSettings,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Audio / Timecode")
        self.resize(520, 480)
        self._devices = list_output_devices()
        self._result = AudioOutputSettings(
            output_device_name=settings.output_device_name,
            music_left_channels=list(settings.music_left_channels),
            music_right_channels=list(settings.music_right_channels),
            ltc_enabled=bool(settings.ltc_enabled),
            ltc_gain=float(settings.ltc_gain),
            ltc_channels=list(settings.ltc_channels),
            mtc_enabled=bool(settings.mtc_enabled),
            midi_port_name=settings.midi_port_name,
        )

        root = QVBoxLayout(self)

        # --- Output device ---
        device_box = QGroupBox("Output Device")
        device_form = QFormLayout(device_box)
        self.device_combo = NoWheelComboBox()
        self.device_combo.addItem("System default", "")
        selected_idx = 0
        for i, dev in enumerate(self._devices):
            self.device_combo.addItem(dev.label, dev.name)
            if settings.output_device_name and (
                settings.output_device_name == dev.name
                or settings.output_device_name.lower() in dev.name.lower()
            ):
                selected_idx = i + 1
        self.device_combo.setCurrentIndex(selected_idx)
        self.device_hint = QLabel("")
        self.device_hint.setStyleSheet("color: #a1a1aa;")
        self.device_hint.setWordWrap(True)
        device_form.addRow("Device", self.device_combo)
        device_form.addRow(self.device_hint)
        root.addWidget(device_box)

        # --- Music routing ---
        music_box = QGroupBox("Music Routing (1-based channel numbers)")
        music_form = QFormLayout(music_box)
        self.music_l = NoWheelComboBox()
        self.music_l.setEditable(True)
        self.music_r = NoWheelComboBox()
        self.music_r.setEditable(True)
        music_form.addRow("Music L →", self.music_l)
        music_form.addRow("Music R →", self.music_r)
        tip = QLabel("Examples: 1 · 1+2 · 3  (empty = mute that side)")
        tip.setStyleSheet("color: #a1a1aa;")
        music_form.addRow(tip)
        root.addWidget(music_box)

        # --- LTC ---
        ltc_box = QGroupBox("Generated LTC")
        ltc_form = QFormLayout(ltc_box)
        self.ltc_enable = QCheckBox("Enable LTC generator")
        self.ltc_enable.setChecked(settings.ltc_enabled)
        self.ltc_channels = NoWheelComboBox()
        self.ltc_channels.setEditable(True)
        self.ltc_gain = QSlider(Qt.Orientation.Horizontal)
        self.ltc_gain.setRange(0, 150)
        self.ltc_gain.setValue(int(round(settings.ltc_gain * 100)))
        self.ltc_gain.setStyleSheet(SLIDER_QSS)
        self.ltc_gain_label = QLabel(f"{int(self.ltc_gain.value())}%")
        gain_row = QHBoxLayout()
        gain_row.addWidget(self.ltc_gain, stretch=1)
        gain_row.addWidget(self.ltc_gain_label)
        ltc_note = QLabel("LTC gain is independent of master Vol.")
        ltc_note.setStyleSheet("color: #a1a1aa;")
        ltc_form.addRow(self.ltc_enable)
        ltc_form.addRow("LTC →", self.ltc_channels)
        ltc_form.addRow("LTC Gain", gain_row)
        ltc_form.addRow(ltc_note)
        root.addWidget(ltc_box)

        # --- MTC ---
        mtc_box = QGroupBox("MIDI Timecode (MTC)")
        mtc_form = QFormLayout(mtc_box)
        self.mtc_enable = QCheckBox("Enable MTC generator")
        self.mtc_enable.setChecked(settings.mtc_enabled)
        self.midi_port = NoWheelComboBox()
        self.midi_port.addItem("(none)", "")
        midi_names = list_midi_output_names()
        midi_sel = 0
        for i, name in enumerate(midi_names):
            self.midi_port.addItem(name, name)
            if settings.midi_port_name and (
                settings.midi_port_name == name or settings.midi_port_name in name
            ):
                midi_sel = i + 1
        if not midi_names:
            self.midi_port.addItem("(no MIDI ports found)", "")
        self.midi_port.setCurrentIndex(midi_sel)
        mtc_form.addRow(self.mtc_enable)
        mtc_form.addRow("MIDI Out", self.midi_port)
        root.addWidget(mtc_box)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

        self.device_combo.currentIndexChanged.connect(self._on_device_changed)
        self.ltc_gain.valueChanged.connect(
            lambda v: self.ltc_gain_label.setText(f"{int(v)}%")
        )
        self._on_device_changed()
        # Restore channel text after populating combos — clamp into this
        # device's range so a saved LTC→3 becomes LTC→2 on a stereo card.
        max_ch = self._current_max_channels()
        left = clamp_output_channels(settings.music_left_channels, max_ch) or [0]
        right_default = [min(1, max_ch - 1)] if max_ch > 0 else [0]
        right = clamp_output_channels(settings.music_right_channels, max_ch) or right_default
        ltc = clamp_output_channels(settings.ltc_channels, max_ch)
        if not ltc:
            ltc = default_ltc_channels_for_device(max_ch)
        self.music_l.setEditText(_channels_to_ui(left) or "1")
        self.music_r.setEditText(_channels_to_ui(right) or ("2" if max_ch >= 2 else "1"))
        self.ltc_channels.setEditText(_channels_to_ui(ltc) or ("2" if max_ch >= 2 else "1"))

    def _current_max_channels(self) -> int:
        name = self.device_combo.currentData() or ""
        if not name:
            chosen = find_output_device(self._devices, name="")
            return chosen.max_output_channels if chosen else 2
        for d in self._devices:
            if d.name == name:
                return d.max_output_channels
        return 2

    def _on_device_changed(self) -> None:
        max_ch = self._current_max_channels()
        left, right, _ltc_default = default_channel_routing(max_ch)
        ltc_default = default_ltc_channels_for_device(max_ch)
        l_txt = _channels_to_ui(left) or "—"
        r_txt = _channels_to_ui(right) or "—"
        ltc_txt = _channels_to_ui(ltc_default) or "—"
        self.device_hint.setText(
            f"{max_ch} output channel(s). "
            f"Default: Music L→{l_txt}, R→{r_txt}; LTC→{ltc_txt}"
            + (" (within CH1–2 on stereo)." if max_ch <= 2 else ".")
        )
        # Refresh suggestion items.
        suggestions = [str(i) for i in range(1, max_ch + 1)]
        if max_ch >= 2:
            suggestions.append("1+2")
        for combo, fallback in (
            (self.music_l, left or [0]),
            (self.music_r, right or ([min(1, max_ch - 1)] if max_ch > 0 else [0])),
            (self.ltc_channels, ltc_default),
        ):
            current = combo.currentText()
            combo.blockSignals(True)
            combo.clear()
            combo.addItems(suggestions)
            combo.setEditText(
                _clamp_channel_ui_text(current, max_ch=max_ch, fallback=fallback)
            )
            combo.blockSignals(False)

    def result_settings(self) -> AudioOutputSettings:
        return self._result

    def _accept(self) -> None:
        max_ch = self._current_max_channels()
        left = _parse_channel_ui(self.music_l.currentText(), max_ch=max_ch)
        right = _parse_channel_ui(self.music_r.currentText(), max_ch=max_ch)
        ltc = _parse_channel_ui(self.ltc_channels.currentText(), max_ch=max_ch)
        if left is None or right is None or ltc is None:
            QMessageBox.warning(
                self,
                "Invalid routing",
                f"Channel numbers must be ≥1 (examples: 1, 1+2, 3). "
                f"Values above {max_ch} are clamped to CH{max_ch}.",
            )
            return
        # Reflect any clamp (e.g. LTC 3→2) back into the fields so the user sees it.
        self.music_l.setEditText(_channels_to_ui(left))
        self.music_r.setEditText(_channels_to_ui(right))
        if self.ltc_enable.isChecked() and not ltc:
            ltc = default_ltc_channels_for_device(max_ch)
        self.ltc_channels.setEditText(_channels_to_ui(ltc))
        if self.ltc_enable.isChecked() and not ltc:
            QMessageBox.warning(
                self,
                "LTC routing",
                "LTC is enabled but this device has no output channels.",
            )
            return
        if self.mtc_enable.isChecked() and not (self.midi_port.currentData() or ""):
            QMessageBox.warning(
                self,
                "MTC port",
                "MTC is enabled but no MIDI output port is selected.",
            )
            return
        self._result = AudioOutputSettings(
            output_device_name=str(self.device_combo.currentData() or ""),
            music_left_channels=left,
            music_right_channels=right,
            ltc_enabled=self.ltc_enable.isChecked(),
            ltc_gain=self.ltc_gain.value() / 100.0,
            ltc_channels=ltc if self.ltc_enable.isChecked() else (
                ltc or default_ltc_channels_for_device(max_ch)
            ),
            mtc_enabled=self.mtc_enable.isChecked(),
            midi_port_name=str(self.midi_port.currentData() or ""),
        )
        self.accept()
