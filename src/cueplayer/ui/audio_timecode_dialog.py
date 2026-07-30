"""Audio output device, channel routing, and LTC / MTC settings dialog."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QScrollArea,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from cueplayer.domain.models import (
    AudioOutputSettings,
    default_ltc_channels_for_device,
)
from cueplayer.playback.devices import (
    OutputDeviceInfo,
    asio_available,
    device_name_score,
    find_output_device,
    list_output_devices,
    list_output_devices_for_picker,
    picker_hostapi_options,
    resolve_output_hostapi,
)
from cueplayer.playback.mtc_output import list_midi_output_names, midi_backend_status
from cueplayer.playback.routing_parse import (
    MUSIC_SOURCE_LABEL,
    derive_channel_modes,
    route_to_ui,
    stereo_routes_from_channel_modes,
)
from cueplayer.ui.checkbox import TickCheckBox
from cueplayer.ui.spinboxes import NoWheelComboBox
from cueplayer.ui.theme import SLIDER_QSS


def _channels_to_ui(channels: list[int]) -> str:
    if not channels:
        return ""
    return "+".join(str(int(c) + 1) for c in channels)


class AudioTimecodeDialog(QDialog):
    """Tools → Audio / Midi / Timecode…"""

    def __init__(
        self,
        settings: AudioOutputSettings,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Audio / Midi / Timecode")
        self.resize(540, 640)
        self._all_devices = list_output_devices(dedupe=False)
        self._devices: list[OutputDeviceInfo] = []
        self._result = AudioOutputSettings(
            output_device_name=settings.output_device_name,
            output_device_index=settings.output_device_index,
            output_hostapi=str(settings.output_hostapi or ""),
            music_l_route=str(settings.music_l_route or "1"),
            music_r_route=str(settings.music_r_route or "2"),
            music_left_channels=list(settings.music_left_channels),
            music_right_channels=list(settings.music_right_channels),
            ltc_enabled=bool(settings.ltc_enabled),
            ltc_source=str(settings.ltc_source),
            ltc_generator_enabled=bool(settings.ltc_generator_enabled),
            ltc_gain=float(settings.ltc_gain),
            ltc_channels=list(settings.ltc_channels),
            ltc_to_mtc_translate=bool(settings.ltc_to_mtc_translate),
            midi_enabled=bool(getattr(settings, "midi_enabled", False)),
            mtc_enabled=bool(settings.mtc_enabled),
            midi_port_name=settings.midi_port_name,
            midi_cue_notes_enabled=bool(settings.midi_cue_notes_enabled),
            midi_cue_channel=int(settings.midi_cue_channel),
            midi_cue_velocity=int(settings.midi_cue_velocity),
            midi_main_base_note=int(settings.midi_main_base_note),
            midi_button_base_note=int(settings.midi_button_base_note),
            output_channel_modes=list(settings.output_channel_modes),
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll_content = QWidget()
        inner = QVBoxLayout(scroll_content)
        inner.setContentsMargins(12, 12, 12, 12)
        inner.setSpacing(8)
        scroll.setWidget(scroll_content)
        root.addWidget(scroll, stretch=1)

        device_box = QGroupBox("Output Device")
        device_form = QFormLayout(device_box)
        self.hostapi_combo = NoWheelComboBox()
        for label, api in picker_hostapi_options():
            self.hostapi_combo.addItem(label, api)
        saved_api = resolve_output_hostapi(settings.output_hostapi)
        selected = False
        for i in range(self.hostapi_combo.count()):
            if self.hostapi_combo.itemData(i) == saved_api:
                self.hostapi_combo.setCurrentIndex(i)
                selected = True
                break
        if not selected and self.hostapi_combo.count():
            self.hostapi_combo.setCurrentIndex(0)

        self.device_combo = NoWheelComboBox()
        self.device_hint = QLabel("")
        self.device_hint.setStyleSheet("color: #a1a1aa;")
        self.device_hint.setWordWrap(True)
        self.driver_hint = QLabel(
            "Default is DirectSound + System default. For a multi-out interface "
            "(e.g. Focusrite), switch Driver to ASIO and pick the device below."
        )
        self.driver_hint.setWordWrap(True)
        self.driver_hint.setStyleSheet("color: #8b949e;")
        if not asio_available():
            self.driver_hint.setText(
                "ASIO not detected by PortAudio — pick ASIO anyway after installing your "
                "interface driver and restarting CuePlayer. "
                "Until then use WASAPI / DirectSound (4ch+ can still route LTC→CH3)."
            )
        device_form.addRow("Driver", self.hostapi_combo)
        device_form.addRow("Device", self.device_combo)
        device_form.addRow(self.device_hint)
        device_form.addRow(self.driver_hint)
        inner.addWidget(device_box)

        stereo_box = QGroupBox("Output Channels")
        self._channel_rows_host = QWidget()
        self._channel_rows_layout = QFormLayout(self._channel_rows_host)
        self._channel_rows_layout.setContentsMargins(0, 0, 0, 0)
        self._channel_mode_combos: list[NoWheelComboBox] = []
        stereo_form = QVBoxLayout(stereo_box)
        stereo_form.addWidget(self._channel_rows_host)
        stereo_tip = QLabel(
            "Assign each physical output channel to Music Source or LTC Source. "
            "Stereo music routing is derived from your picks (e.g. CH1=Music, CH2=LTC). "
            "Music Source = music-only (striped LTC removed from that leg)."
        )
        stereo_tip.setStyleSheet("color: #a1a1aa;")
        stereo_tip.setWordWrap(True)
        stereo_form.addWidget(stereo_tip)
        inner.addWidget(stereo_box)

        mtc_box = QGroupBox("MIDI Output")
        mtc_form = QFormLayout(mtc_box)
        self.midi_on = TickCheckBox("MIDI On")
        self.midi_on.setChecked(bool(getattr(settings, "midi_enabled", False)))
        self.midi_on.setToolTip(
            "Master switch — MTC, Translate, and Cue Notes only work when MIDI is on."
        )
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

        self.mtc_enable = TickCheckBox("MTC Generator")
        self.mtc_enable.setChecked(settings.mtc_enabled)
        self.mtc_enable.setToolTip(
            "Send MIDI Timecode from Song Start TC + playhead (generator numbers)."
        )
        self.ltc_to_mtc_translate = TickCheckBox("Translate file LTC → MTC")
        self.ltc_to_mtc_translate.setChecked(bool(settings.ltc_to_mtc_translate))
        self.ltc_to_mtc_translate.setToolTip(
            "Decode the LTC stripe from the audio file and send those HH:MM:SS:FF "
            "numbers as MTC. Set LTC source to From file. Does not need LTC output."
        )
        self.midi_notes_enable = TickCheckBox("Send MIDI Cue Notes")
        self.midi_notes_enable.setChecked(bool(settings.midi_cue_notes_enabled))
        self.midi_notes_enable.setToolTip(
            "Short Note On/Off when crossing enabled mark lanes (Mark Manager MIDI column)."
        )
        self.midi_cue_channel = NoWheelComboBox()
        for ch in range(1, 17):
            self.midi_cue_channel.addItem(f"CH {ch}", ch)
        ch_idx = max(0, min(15, int(settings.midi_cue_channel) - 1))
        self.midi_cue_channel.setCurrentIndex(ch_idx)
        self.midi_main_base = NoWheelComboBox()
        self.midi_button_base = NoWheelComboBox()
        for note in range(0, 128):
            label = f"{note}"
            self.midi_main_base.addItem(label, note)
            self.midi_button_base.addItem(label, note)
        self.midi_main_base.setCurrentIndex(max(0, min(127, int(settings.midi_main_base_note))))
        self.midi_button_base.setCurrentIndex(
            max(0, min(127, int(settings.midi_button_base_note)))
        )

        mtc_form.addRow(self.midi_on)
        mtc_form.addRow("MIDI Out", self.midi_port)
        mtc_form.addRow(self.mtc_enable)
        mtc_form.addRow(self.ltc_to_mtc_translate)
        mtc_form.addRow(self.midi_notes_enable)
        mtc_form.addRow("Notes channel", self.midi_cue_channel)
        mtc_form.addRow("Main base note", self.midi_main_base)
        mtc_form.addRow("Button base note", self.midi_button_base)
        mtc_sync_hint = QLabel(
            "Pick MIDI Out anytime (even when MIDI On is off). MIDI On enables "
            "sending: MTC Generator (Song Start TC), Translate (file LTC stripe), "
            "and/or Cue Notes."
        )
        mtc_sync_hint.setWordWrap(True)
        mtc_sync_hint.setStyleSheet("color: #a1a1aa;")
        mtc_form.addRow(mtc_sync_hint)
        midi_hint = QLabel(midi_backend_status())
        midi_hint.setWordWrap(True)
        midi_hint.setStyleSheet("color: #a1a1aa;")
        mtc_form.addRow(midi_hint)
        inner.addWidget(mtc_box)

        ltc_box = QGroupBox("LTC Output")
        ltc_form = QFormLayout(ltc_box)
        self.ltc_enable = TickCheckBox("Enable LTC on output")
        self.ltc_enable.setChecked(settings.ltc_enabled)
        self.ltc_source = NoWheelComboBox()
        self.ltc_source.addItem("Internal generator", "generator")
        self.ltc_source.addItem("From file — auto-detect L/R", "auto")
        self.ltc_source.addItem("From file — Left channel", "source_left")
        self.ltc_source.addItem("From file — Right channel", "source_right")
        for i in range(self.ltc_source.count()):
            if self.ltc_source.itemData(i) == settings.ltc_source:
                self.ltc_source.setCurrentIndex(i)
                break
        self.ltc_generator_enable = TickCheckBox("Enable internal LTC generator")
        self.ltc_generator_enable.setChecked(settings.ltc_generator_enabled)
        self.ltc_generator_enable.setToolTip(
            "Only when LTC source is Internal generator. File pass-through ignores this."
        )
        self.ltc_gain = QSlider(Qt.Orientation.Horizontal)
        self.ltc_gain.setRange(0, 150)
        self.ltc_gain.setValue(int(round(settings.ltc_gain * 100)))
        self.ltc_gain.setStyleSheet(SLIDER_QSS)
        self.ltc_gain_label = QLabel(f"{int(self.ltc_gain.value())}%")
        gain_row = QHBoxLayout()
        gain_row.addWidget(self.ltc_gain, stretch=1)
        gain_row.addWidget(self.ltc_gain_label)
        ltc_note = QLabel(
            "Enable LTC on output, then pick LTC Source on an output channel above. "
            "Use file source for striped audio; use Internal generator only when needed."
        )
        ltc_note.setStyleSheet("color: #a1a1aa;")
        ltc_note.setWordWrap(True)
        ltc_form.addRow(self.ltc_enable)
        ltc_form.addRow("LTC source", self.ltc_source)
        ltc_form.addRow(self.ltc_generator_enable)
        ltc_form.addRow("LTC Gain", gain_row)
        ltc_form.addRow(ltc_note)
        inner.addWidget(ltc_box)
        inner.addStretch(1)

        btn_bar = QWidget()
        btn_bar.setStyleSheet("border-top: 1px solid #27272a;")
        btn_layout = QVBoxLayout(btn_bar)
        btn_layout.setContentsMargins(12, 8, 12, 8)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        btn_layout.addWidget(buttons)
        root.addWidget(btn_bar)

        self.hostapi_combo.currentIndexChanged.connect(lambda _idx: self._reload_devices())
        self.device_combo.currentIndexChanged.connect(self._on_device_changed)
        self.ltc_source.currentIndexChanged.connect(self._on_ltc_source_changed)
        self.ltc_enable.toggled.connect(self._on_ltc_source_changed)
        self.ltc_enable.toggled.connect(lambda _checked: self._on_device_changed())
        self.midi_on.toggled.connect(self._sync_midi_ui)
        self.midi_notes_enable.toggled.connect(self._sync_midi_ui)
        self.ltc_gain.valueChanged.connect(
            lambda v: self.ltc_gain_label.setText(f"{int(v)}%")
        )
        self._saved_channel_modes = derive_channel_modes(
            settings, max_ch=max(2, len(settings.output_channel_modes) or 2)
        )
        self._reload_devices()
        self._on_ltc_source_changed()
        self._combo_hostapi = resolve_output_hostapi(str(settings.output_hostapi or ""))
        self._sync_midi_ui()

    def _sync_midi_ui(self) -> None:
        midi_on = self.midi_on.isChecked()
        # Port can be chosen before MIDI On — so turning On later already has a device.
        self.midi_port.setEnabled(True)
        for widget in (
            self.mtc_enable,
            self.ltc_to_mtc_translate,
            self.midi_notes_enable,
        ):
            widget.setEnabled(midi_on)
        notes_on = midi_on and self.midi_notes_enable.isChecked()
        for widget in (
            self.midi_cue_channel,
            self.midi_main_base,
            self.midi_button_base,
        ):
            widget.setEnabled(notes_on)

    def _current_hostapi(self) -> str:
        return resolve_output_hostapi(str(self.hostapi_combo.currentData() or ""))

    def _reload_devices(self) -> None:
        api = self._current_hostapi()
        api_changed = api != getattr(self, "_combo_hostapi", None)
        prev_idx = None if api_changed else self.device_combo.currentData()
        prev_chosen = None if api_changed else self._chosen_device()
        target_name = (prev_chosen.name if prev_chosen else "") or self._result.output_device_name or ""
        self._combo_hostapi = api
        self._devices = list_output_devices_for_picker(api)
        self.device_combo.blockSignals(True)
        self.device_combo.clear()
        self.device_combo.addItem("System default", None)
        select = 0
        best_score = -1
        for i, dev in enumerate(self._devices):
            self.device_combo.addItem(dev.label, dev.index)
            score = device_name_score(target_name, dev.name) if target_name else 0
            if score > best_score:
                best_score = score
                select = i + 1
            elif not api_changed and prev_idx is not None and dev.index == prev_idx and best_score <= 0:
                select = i + 1
        self.device_combo.setCurrentIndex(select)
        self.device_combo.blockSignals(False)
        self._on_device_changed()

    def _chosen_device(self) -> OutputDeviceInfo | None:
        idx = self.device_combo.currentData()
        if idx is None:
            return find_output_device(self._devices, name="")
        for dev in self._devices:
            if dev.index == idx:
                return dev
        return find_output_device(self._devices, name=str(self.device_combo.currentData() or ""))

    def _current_max_channels(self) -> int:
        """Channels on the device the user picked — not a higher sibling endpoint."""
        chosen = self._chosen_device()
        if chosen is None:
            return 2
        return max(1, int(chosen.max_output_channels))

    def _on_ltc_source_changed(self) -> None:
        is_generator = self.ltc_source.currentData() == "generator"
        self.ltc_generator_enable.setVisible(is_generator)
        if is_generator:
            self.ltc_generator_enable.setEnabled(self.ltc_enable.isChecked())

    def _channel_mode_items(self) -> list[tuple[str, str]]:
        return [
            ("Off", "off"),
            (MUSIC_SOURCE_LABEL, "music_source"),
            ("LTC Source", "ltc"),
        ]

    def _current_channel_modes(self) -> list[str]:
        modes: list[str] = []
        for combo in self._channel_mode_combos:
            modes.append(str(combo.currentData() or "off"))
        return modes

    def _rebuild_channel_rows(self, *, preserve: bool = True) -> None:
        max_ch = self._current_max_channels()
        prev = self._current_channel_modes() if preserve and self._channel_mode_combos else []
        if not prev:
            prev = list(getattr(self, "_saved_channel_modes", []) or [])
        if len(prev) < max_ch:
            derived = derive_channel_modes(self._result, max_ch=max_ch)
            for i in range(len(prev), max_ch):
                prev.append(derived[i] if i < len(derived) else "off")
        while len(prev) < max_ch:
            prev.append("off")

        while self._channel_rows_layout.count():
            item = self._channel_rows_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._channel_mode_combos.clear()

        items = self._channel_mode_items()
        for ch in range(max_ch):
            combo = NoWheelComboBox()
            for label, mode in items:
                combo.addItem(label, mode)
            mode = prev[ch] if ch < len(prev) else "off"
            idx = max(0, combo.findData(mode))
            combo.setCurrentIndex(idx)
            self._channel_mode_combos.append(combo)
            self._channel_rows_layout.addRow(f"CH {ch + 1}", combo)

    def _on_device_changed(self) -> None:
        max_ch = self._current_max_channels()
        ltc_default = default_ltc_channels_for_device(max_ch)
        chosen = self._chosen_device()
        api_txt = chosen.hostapi_name.replace("Windows ", "") if chosen else "—"
        if max_ch >= 3:
            wire = f"Typical LTC wire: CH {_channels_to_ui(ltc_default) or '—'}."
        else:
            wire = "Stereo — use Music Source on both channels; LTC needs a multi-out interface."
        self.device_hint.setText(f"{max_ch} output channel(s) via {api_txt}. {wire}")
        self._rebuild_channel_rows(preserve=True)

    def result_settings(self) -> AudioOutputSettings:
        return self._result

    def _accept(self) -> None:
        max_ch = self._current_max_channels()
        modes = self._current_channel_modes()
        while len(modes) < max_ch:
            modes.append("off")
        ltc_channels = [i for i, m in enumerate(modes[:max_ch]) if m == "ltc"]
        left_kind, left_ch, right_kind, right_ch, bus_ltc = stereo_routes_from_channel_modes(
            modes,
            max_ch=max_ch,
        )
        ltc = bus_ltc or ltc_channels[:1]
        if self.ltc_enable.isChecked() and not ltc:
            QMessageBox.information(
                self,
                "LTC routing",
                "LTC is enabled but no output channel is set to LTC Source — "
                "timecode will not be sent to the speakers. "
                "Assign LTC Source on a channel above when you need a wire.",
            )
        music_l_route = route_to_ui(left_kind, left_ch)
        music_r_route = route_to_ui(right_kind, right_ch)
        midi_on = self.midi_on.isChecked()
        port = str(self.midi_port.currentData() or "")
        if midi_on and not port:
            QMessageBox.warning(
                self,
                "MIDI",
                "MIDI is on but no MIDI output port is selected.",
            )
            return
        if midi_on and self.mtc_enable.isChecked() and not port:
            QMessageBox.warning(self, "MTC", "MTC Generator needs a MIDI output port.")
            return
        if midi_on and self.ltc_to_mtc_translate.isChecked() and not port:
            QMessageBox.warning(self, "Translate", "LTC → MTC needs a MIDI output port.")
            return
        if midi_on and self.midi_notes_enable.isChecked() and not port:
            QMessageBox.warning(self, "MIDI cue notes", "Cue notes need a MIDI output port.")
            return
        chosen = self._chosen_device()
        self._result = AudioOutputSettings(
            output_device_name=chosen.name if chosen is not None else "",
            output_device_index=chosen.index if chosen is not None else None,
            output_hostapi=resolve_output_hostapi(str(self.hostapi_combo.currentData() or "")),
            music_l_route=music_l_route,
            music_r_route=music_r_route,
            music_left_channels=left_ch if left_kind == "channels" else [],
            music_right_channels=right_ch if right_kind == "channels" else [],
            ltc_enabled=self.ltc_enable.isChecked(),
            ltc_source=str(self.ltc_source.currentData() or "generator"),
            ltc_generator_enabled=self.ltc_generator_enable.isChecked(),
            ltc_gain=self.ltc_gain.value() / 100.0,
            ltc_channels=ltc if self.ltc_enable.isChecked() else [],
            ltc_to_mtc_translate=self.ltc_to_mtc_translate.isChecked(),
            midi_enabled=midi_on,
            mtc_enabled=self.mtc_enable.isChecked(),
            midi_port_name=port,
            midi_cue_notes_enabled=self.midi_notes_enable.isChecked(),
            midi_cue_channel=int(self.midi_cue_channel.currentData() or 1),
            midi_cue_velocity=100,
            midi_main_base_note=int(self.midi_main_base.currentData() or 36),
            midi_button_base_note=int(self.midi_button_base.currentData() or 48),
            output_channel_modes=modes[:max_ch],
        )
        self.accept()
