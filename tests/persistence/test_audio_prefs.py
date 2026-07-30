"""Machine-global Audio / Midi / Timecode preferences."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from cueplayer.domain.models import AudioOutputSettings, Project
from cueplayer.persistence import audio_prefs
from cueplayer.playback import devices as devices_mod


@pytest.fixture
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def _isolate_qsettings(tmp_path, monkeypatch):
    """Keep tests from touching the developer's real CuePlayer settings."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    QSettings.setPath(
        QSettings.Format.IniFormat,
        QSettings.Scope.UserScope,
        str(tmp_path / "qs"),
    )
    # Force Ini under our temp path via organization/app still works if we
    # monkeypatch the settings factory.
    def _settings():
        s = QSettings(str(tmp_path / "audio_prefs.ini"), QSettings.Format.IniFormat)
        return s

    monkeypatch.setattr(audio_prefs, "_settings", _settings)
    yield


def test_first_run_defaults_directsound_and_system_default(monkeypatch, app) -> None:
    monkeypatch.setattr(
        devices_mod,
        "hostapi_names",
        lambda: ["ASIO", "Windows WASAPI", "Windows DirectSound"],
    )
    settings = audio_prefs.load_global_audio_output()
    assert settings.output_hostapi == "Windows DirectSound"
    assert settings.output_device_name == ""
    assert settings.output_device_index is None


def test_save_load_roundtrip_survives_new_project(monkeypatch, app) -> None:
    monkeypatch.setattr(
        devices_mod,
        "hostapi_names",
        lambda: ["Windows DirectSound", "Windows WASAPI"],
    )
    saved = AudioOutputSettings(
        output_hostapi="Windows DirectSound",
        output_device_name="",
        midi_port_name="loopMIDI Port",
        midi_enabled=False,
        mtc_enabled=True,
    )
    audio_prefs.save_global_audio_output(saved)

    project_a = Project.create("A")
    audio_prefs.apply_global_audio_to_project(project_a)
    assert project_a.audio_output.midi_port_name == "loopMIDI Port"
    assert project_a.audio_output.mtc_enabled is True

    project_b = Project.create("B")
    audio_prefs.apply_global_audio_to_project(project_b)
    assert project_b.audio_output.midi_port_name == "loopMIDI Port"
    assert project_b.audio_output.output_hostapi == "Windows DirectSound"
