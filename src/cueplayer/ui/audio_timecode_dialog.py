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
from cueplayer.playback.devices import (
    OutputDeviceInfo,
    asio_available,
    device_name_score,
    find_output_device,
    list_output_devices,
    list_output_devices_for_picker,
    picker_hostapi_options,
    resolve_output_hostapi,
    resolve_output_endpoint_for_channels,
    upgrade_device_for_channels,
)
from cueplayer.playback.mtc_output import list_midi_output_names, midi_backend_status
from cueplayer.playback.routing_parse import (
    LTC_LABEL,
    MUSIC_SOURCE_LABEL,
    is_ltc_route,
    is_music_source_route,
    parse_channel_ui,
    parse_stereo_route,
    route_to_ui,
)
from cueplayer.ui.checkbox import TickCheckBox
from cueplayer.ui.spinboxes import NoWheelComboBox
from cueplayer.ui.theme import SLIDER_QSS


def _channels_to_ui(channels: list[int]) -> str:
    if not channels:
        return ""
    return "+".join(str(int(c) + 1) for c in channels)


def _clamp_channel_ui_text(
    text: str, *, max_ch: int, fallback: list[int] | None = None
) -> str:
    if is_music_source_route(text) or is_ltc_route(text):
        return text.strip()
    parsed = parse_channel_ui(text, max_ch=max_ch)
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
            mtc_enabled=bool(settings.mtc_enabled),
            midi_port_name=settings.midi_port_name,
            midi_cue_notes_enabled=bool(settings.midi_cue_notes_enabled),
            midi_cue_channel=int(settings.midi_cue_channel),
            midi_cue_velocity=int(settings.midi_cue_velocity),
            midi_main_base_note=int(settings.midi_main_base_note),
            midi_button_base_note=int(settings.midi_button_base_note),
        )

        root = QVBoxLayout(self)

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
            "Driver: choose ASIO, then pick your interface (e.g. Focusrite) under Device. "
            "Use WASAPI or DirectSound only when ASIO is unavailable."
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
        root.addWidget(device_box)

        stereo_box = QGroupBox("Stereo Output (L / R legs)")
        stereo_form = QFormLayout(stereo_box)
        self.music_l = NoWheelComboBox()
        self.music_l.setEditable(True)
        self.music_r = NoWheelComboBox()
        self.music_r.setEditable(True)
        stereo_form.addRow("L →", self.music_l)
        stereo_form.addRow("R →", self.music_r)
        stereo_tip = QLabel(
            "Music Source = music-only (striped LTC removed). "
            "LTC = pass file timecode to that leg (e.g. 3.5mm split: L=Music Source, R=LTC). "
            "Or use channel numbers 1 · 2 · 3 · 1+2. "
            "Dedicated LTC → channel stays exclusive (music never shares that wire)."
        )
        stereo_tip.setStyleSheet("color: #a1a1aa;")
        stereo_tip.setWordWrap(True)
        stereo_form.addRow(stereo_tip)
        root.addWidget(stereo_box)

        ltc_box = QGroupBox("LTC Output")
        ltc_form = QFormLayout(ltc_box)
        self.ltc_enable = TickCheckBox("Enable LTC on output")
        self.ltc_enable.setChecked(settings.ltc_enabled)
        self.ltc_channels = NoWheelComboBox()
        self.ltc_channels.setEditable(True)
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
            "Enable LTC on output + LTC→CH3 sends timecode to your interface. "
            "Use file source for striped audio; use Internal generator only when needed."
        )
        ltc_note.setStyleSheet("color: #a1a1aa;")
        ltc_note.setWordWrap(True)
        ltc_form.addRow(self.ltc_enable)
        ltc_form.addRow("LTC →", self.ltc_channels)
        ltc_form.addRow("LTC source", self.ltc_source)
        ltc_form.addRow(self.ltc_generator_enable)
        ltc_form.addRow("LTC Gain", gain_row)
        ltc_form.addRow(ltc_note)
        root.addWidget(ltc_box)

        mtc_box = QGroupBox("MIDI Timecode (MTC)")
        mtc_form = QFormLayout(mtc_box)
        self.mtc_enable = TickCheckBox("Enable MTC generator")
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
        mtc_sync_hint = QLabel(
            "MTC uses the same song start timecode and FPS as LTC "
            "(Song Edit → Start TC / FPS). Numbers match LTC when both are enabled."
        )
        mtc_sync_hint.setWordWrap(True)
        mtc_sync_hint.setStyleSheet("color: #a1a1aa;")
        mtc_form.addRow(mtc_sync_hint)
        midi_hint = QLabel(midi_backend_status())
        midi_hint.setWordWrap(True)
        midi_hint.setStyleSheet("color: #a1a1aa;")
        mtc_form.addRow(midi_hint)
        root.addWidget(mtc_box)

        notes_box = QGroupBox("MIDI Cue Notes (MA record / link)")
        notes_form = QFormLayout(notes_box)
        self.midi_notes_enable = TickCheckBox("Send MIDI notes when crossing enabled mark lanes")
        self.midi_notes_enable.setChecked(bool(settings.midi_cue_notes_enabled))
        self.midi_notes_enable.setToolTip(
            "Enable per-lane in Mark Manager (MIDI column). "
            "Uses the same MIDI Out as MTC when both are on."
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
        notes_form.addRow(self.midi_notes_enable)
        notes_form.addRow("Channel", self.midi_cue_channel)
        notes_form.addRow("Main base note", self.midi_main_base)
        notes_form.addRow("Button base note", self.midi_button_base)
        notes_tip = QLabel(
            "Default notes: Main = base + (lane#−1), Button = base + (lane#−1). "
            "Override per lane in Mark Manager. Short Note On/Off pulse on each mark."
        )
        notes_tip.setWordWrap(True)
        notes_tip.setStyleSheet("color: #a1a1aa;")
        notes_form.addRow(notes_tip)
        root.addWidget(notes_box)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

        self.hostapi_combo.currentIndexChanged.connect(lambda _idx: self._reload_devices())
        self.device_combo.currentIndexChanged.connect(self._on_device_changed)
        self.ltc_source.currentIndexChanged.connect(self._on_ltc_source_changed)
        self.ltc_enable.toggled.connect(self._on_ltc_source_changed)
        self.ltc_gain.valueChanged.connect(
            lambda v: self.ltc_gain_label.setText(f"{int(v)}%")
        )
        self._reload_devices()
        self._on_ltc_source_changed()
        self.music_l.setEditText(settings.music_l_route or "1")
        self.music_r.setEditText(settings.music_r_route or "2")
        max_ch = self._current_max_channels()
        ltc = clamp_output_channels(settings.ltc_channels, max_ch)
        if not ltc:
            ltc = default_ltc_channels_for_device(max_ch)
        self.ltc_channels.setEditText(_channels_to_ui(ltc) or ("3" if max_ch >= 3 else "1"))
        self._combo_hostapi = resolve_output_hostapi(str(settings.output_hostapi or ""))

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
        chosen = self._chosen_device()
        if chosen is None:
            return 2
        api = self._current_hostapi()
        need = 3 if self.ltc_enable.isChecked() else 1
        endpoint = resolve_output_endpoint_for_channels(
            preferred_name=chosen.name,
            min_channels=need,
            samplerate=48000.0,
            raw_devices=self._all_devices,
            hostapi=api,
        )
        if endpoint is not None:
            return endpoint.max_output_channels
        return upgrade_device_for_channels(
            chosen,
            min_channels=need,
            raw_devices=self._all_devices,
            hostapi=api,
        ).max_output_channels

    def _on_ltc_source_changed(self) -> None:
        is_generator = self.ltc_source.currentData() == "generator"
        self.ltc_generator_enable.setVisible(is_generator)
        if is_generator:
            self.ltc_generator_enable.setEnabled(self.ltc_enable.isChecked())

    def _stereo_suggestions(self, max_ch: int) -> list[str]:
        items = [MUSIC_SOURCE_LABEL, LTC_LABEL]
        items.extend(str(i) for i in range(1, max_ch + 1))
        if max_ch >= 2:
            items.append("1+2")
        return items

    def _on_device_changed(self) -> None:
        max_ch = self._current_max_channels()
        left, right, _ = default_channel_routing(max_ch)
        ltc_default = default_ltc_channels_for_device(max_ch)
        chosen = self._chosen_device()
        api_txt = chosen.hostapi_name.replace("Windows ", "") if chosen else "—"
        self.device_hint.setText(
            f"{max_ch} output channel(s) via {api_txt}. "
            f"Default LTC→{_channels_to_ui(ltc_default) or '—'}."
        )
        suggestions = self._stereo_suggestions(max_ch)
        for combo, fallback, side in (
            (self.music_l, left or [0], "l"),
            (self.music_r, right or ([min(1, max_ch - 1)] if max_ch > 0 else [0]), "r"),
        ):
            current = combo.currentText()
            combo.blockSignals(True)
            combo.clear()
            combo.addItems(suggestions)
            if is_music_source_route(current) or is_ltc_route(current):
                combo.setEditText(current)
            else:
                combo.setEditText(
                    _clamp_channel_ui_text(current, max_ch=max_ch, fallback=fallback)
                )
            combo.blockSignals(False)
        ltc_suggestions = [str(i) for i in range(1, max_ch + 1)]
        combo = self.ltc_channels
        current = combo.currentText()
        combo.blockSignals(True)
        combo.clear()
        combo.addItems(ltc_suggestions)
        combo.setEditText(
            _clamp_channel_ui_text(current, max_ch=max_ch, fallback=ltc_default)
        )
        combo.blockSignals(False)

    def result_settings(self) -> AudioOutputSettings:
        return self._result

    def _accept(self) -> None:
        max_ch = self._current_max_channels()
        left_parsed = parse_stereo_route(self.music_l.currentText(), side="l", max_ch=max_ch)
        right_parsed = parse_stereo_route(self.music_r.currentText(), side="r", max_ch=max_ch)
        ltc = parse_channel_ui(self.ltc_channels.currentText(), max_ch=max_ch)
        if left_parsed is None or right_parsed is None or ltc is None:
            QMessageBox.warning(
                self,
                "Invalid routing",
                "Use Music Source, LTC, or channel numbers (1, 1+2, 3).",
            )
            return
        left_kind, left_ch = left_parsed
        right_kind, right_ch = right_parsed
        self.music_l.setEditText(route_to_ui(left_kind, left_ch, legacy_text=self.music_l.currentText()))
        self.music_r.setEditText(route_to_ui(right_kind, right_ch, legacy_text=self.music_r.currentText()))
        if self.ltc_enable.isChecked() and not ltc:
            ltc = default_ltc_channels_for_device(max_ch)
        if self.ltc_enable.isChecked() and ltc and len(ltc) > 1:
            QMessageBox.warning(
                self,
                "LTC routing",
                "LTC is mono — route to one channel (e.g. 3 for Focusrite CH3).",
            )
            return
        self.ltc_channels.setEditText(_channels_to_ui(ltc))
        if self.ltc_enable.isChecked() and not ltc:
            QMessageBox.warning(self, "LTC routing", "LTC is enabled but no output channel is set.")
            return
        if self.mtc_enable.isChecked() and not (self.midi_port.currentData() or ""):
            QMessageBox.warning(self, "MTC port", "MTC is enabled but no MIDI output port is selected.")
            return
        if self.midi_notes_enable.isChecked() and not (self.midi_port.currentData() or ""):
            QMessageBox.warning(
                self,
                "MIDI cue notes",
                "MIDI cue notes are enabled but no MIDI output port is selected.",
            )
            return
        chosen = self._chosen_device()
        self._result = AudioOutputSettings(
            output_device_name=chosen.name if chosen is not None else "",
            output_device_index=chosen.index if chosen is not None else None,
            output_hostapi=resolve_output_hostapi(str(self.hostapi_combo.currentData() or "")),
            music_l_route=self.music_l.currentText().strip() or "1",
            music_r_route=self.music_r.currentText().strip() or "2",
            music_left_channels=left_ch if left_kind == "channels" else [],
            music_right_channels=right_ch if right_kind == "channels" else [],
            ltc_enabled=self.ltc_enable.isChecked(),
            ltc_source=str(self.ltc_source.currentData() or "generator"),
            ltc_generator_enabled=self.ltc_generator_enable.isChecked(),
            ltc_gain=self.ltc_gain.value() / 100.0,
            ltc_channels=ltc if self.ltc_enable.isChecked() else (
                ltc or default_ltc_channels_for_device(max_ch)
            ),
            mtc_enabled=self.mtc_enable.isChecked(),
            midi_port_name=str(self.midi_port.currentData() or ""),
            midi_cue_notes_enabled=self.midi_notes_enable.isChecked(),
            midi_cue_channel=int(self.midi_cue_channel.currentData() or 1),
            midi_cue_velocity=100,
            midi_main_base_note=int(self.midi_main_base.currentData() or 36),
            midi_button_base_note=int(self.midi_button_base.currentData() or 48),
        )
        self.accept()
