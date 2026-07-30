"""Audio / Midi / Timecode dialog MIDI Out stays usable when MIDI On is off."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from cueplayer.domain.models import AudioOutputSettings
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
