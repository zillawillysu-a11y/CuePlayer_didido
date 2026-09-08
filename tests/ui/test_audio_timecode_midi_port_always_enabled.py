"""Audio / Midi / Timecode dialog MIDI Out stays usable when MIDI On is off."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from cueplayer.domain.models import AudioOutputSettings
from cueplayer.playback.artnet_timecode import Ipv4Interface
from cueplayer.ui.audio_timecode_dialog import AudioTimecodeDialog


@pytest.fixture
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_midi_out_enabled_when_midi_on_unchecked(app: QApplication, monkeypatch) -> None:
    monkeypatch.setattr(
        "cueplayer.ui.audio_timecode_dialog.list_midi_output_names",
        lambda: ["Port A", "Port B"],
    )
    monkeypatch.setattr(
        "cueplayer.ui.audio_timecode_dialog.picker_hostapi_options",
        lambda: [("DirectSound", "Windows DirectSound")],
    )
    monkeypatch.setattr(
        "cueplayer.ui.audio_timecode_dialog.list_output_devices_for_picker",
        lambda _api: [],
    )
    monkeypatch.setattr(
        "cueplayer.ui.audio_timecode_dialog.resolve_output_hostapi",
        lambda hostapi: hostapi or "Windows DirectSound",
    )
    settings = AudioOutputSettings(midi_enabled=False, midi_port_name="")
    dialog = AudioTimecodeDialog(settings)
    assert dialog.midi_on.isChecked() is False
    assert dialog.midi_port.isEnabled() is True
    dialog.midi_on.setChecked(True)
    assert dialog.midi_port.isEnabled() is True
    dialog.midi_on.setChecked(False)
    assert dialog.midi_port.isEnabled() is True


def test_artnet_output_is_independent_and_uses_interface_broadcast(
    app: QApplication, monkeypatch
) -> None:
    monkeypatch.setattr(
        "cueplayer.ui.audio_timecode_dialog.list_midi_output_names", lambda: []
    )
    monkeypatch.setattr(
        "cueplayer.ui.audio_timecode_dialog.picker_hostapi_options",
        lambda: [("DirectSound", "Windows DirectSound")],
    )
    monkeypatch.setattr(
        "cueplayer.ui.audio_timecode_dialog.list_output_devices_for_picker",
        lambda _api: [],
    )
    monkeypatch.setattr(
        "cueplayer.ui.audio_timecode_dialog.resolve_output_hostapi",
        lambda hostapi: hostapi or "Windows DirectSound",
    )
    interface = Ipv4Interface(
        "Art-Net NIC", "2.0.0.233", "255.0.0.0", "2.255.255.255"
    )
    monkeypatch.setattr(
        "cueplayer.ui.audio_timecode_dialog.list_ipv4_interfaces",
        lambda: [interface],
    )
    monkeypatch.setattr(
        "cueplayer.playback.artnet_timecode.list_ipv4_interfaces",
        lambda: [interface],
    )

    dialog = AudioTimecodeDialog(AudioOutputSettings(midi_enabled=False))
    assert dialog.ltc_to_mtc_translate.isEnabled() is False
    dialog.artnet_enable.setChecked(True)
    assert dialog.midi_on.isChecked() is False
    assert dialog.ltc_to_mtc_translate.isEnabled() is True
    dialog.ltc_to_mtc_translate.setChecked(True)
    assert dialog.artnet_local_ip.currentData() == "2.0.0.233"
    assert dialog.artnet_destination_ip.text() == "2.255.255.255"
    assert "Ready:" in dialog.artnet_status.text()

    dialog._accept()
    result = dialog.result_settings()
    assert result.artnet_timecode_enabled is True
    assert result.artnet_timecode_local_ip == "2.0.0.233"
    assert result.artnet_timecode_destination_mode == "broadcast"
    assert result.artnet_timecode_destination_ip == "2.255.255.255"
    assert result.ltc_to_mtc_translate is True
