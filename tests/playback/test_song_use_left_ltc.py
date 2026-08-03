"""Per-song Left LTC checkbox routes file Left to settings LTC channel."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication, QCheckBox

from cueplayer.domain.models import AudioOutputSettings, AudioTrack, Project, Song
from cueplayer.media.audio_loader import AudioBuffer, build_peak_pyramid, load_audio
from cueplayer.persistence.project_store import project_from_dict, project_to_dict
from cueplayer.playback import audio_engine as eng_mod
from cueplayer.playback.devices import OutputDeviceInfo
from cueplayer.ui.song_edit_dialog import SongDraft, SongEditDialog

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "fixtures" / "media" / "中文測試" / "LTC左_音樂右_測試.wav"


def _device() -> OutputDeviceInfo:
    return OutputDeviceInfo(
        index=0,
        name="Test",
        max_output_channels=8,
        default_samplerate=48000.0,
        hostapi_name="Test",
    )


@pytest.fixture
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_song_edit_dialog_has_left_ltc_checkbox(app: QApplication) -> None:
    dialog = SongEditDialog(
        [SongDraft(name="Opening", setlist_number=1.0, use_left_ltc=True)],
        title="Edit Song",
    )
    from cueplayer.ui import song_edit_dialog as sed

    wrap = dialog.table.cellWidget(0, sed._COL_LEFT_LTC)
    assert wrap is not None
    check = wrap.findChild(QCheckBox)
    assert check is not None
    assert check.isChecked() is True


def test_use_left_ltc_persists_in_project() -> None:
    project = Project.create("LTC Flag")
    project.songs[0].use_left_ltc = True
    restored = project_from_dict(project_to_dict(project))
    assert restored.songs[0].use_left_ltc is True


def test_song_use_left_ltc_routes_left_to_ltc_bus(monkeypatch, app: QApplication) -> None:
    monkeypatch.setattr(eng_mod, "list_output_devices", lambda dedupe=True: [_device()])
    monkeypatch.setattr(eng_mod.sd, "check_output_settings", lambda **kwargs: None)

    assert FIXTURE.is_file()
    buf = load_audio(FIXTURE)
    song = Song.create("Opening")
    song.use_left_ltc = True
    song.audio_tracks = [
        AudioTrack(id="main", name="opening", path=FIXTURE, role="main")
    ]

    engine = eng_mod.AudioEngine()
    engine.apply_audio_settings(
        AudioOutputSettings(
            output_device_name="Test",
            music_l_route="1",
            music_r_route="2",
            ltc_enabled=True,
            ltc_source="generator",
            ltc_generator_enabled=True,
            ltc_channels=[2],
        )
    )
    engine.set_song(song)
    engine.set_buffer(buf)
    engine.flush_deferred_buffer_setup()
    engine.refresh_song_ltc_routing()

    assert engine._effective_ltc_source_channel() == 0
    assert not engine._uses_generated_ltc()
    assert engine._route.get(2) == [2]  # SRC_LTC_BUS → CH3
    # Speakers are Music Source (file music), never sharing the LTC wire.
    assert engine._route.get(3) == [0, 1]  # SRC_FILE_MUSIC → CH1+CH2
    assert 0 not in (engine._route.get(0) or [])  # no raw Music L on LTC path
    assert 2 not in (engine._route.get(3) or [])

    ltc = engine._ltc_chunk(0, 2048)
    music = engine._music_chunk(0, 2048, engine._sample_rate())
    assert np.any(ltc != 0.0)
    # Music bus is Right only (Left stripped as LTC).
    assert np.allclose(music[:, 0], music[:, 1])
    assert engine._cached_music_indices == (1, 1)


def test_two_channel_device_keeps_ltc_exclusive(monkeypatch, app: QApplication) -> None:
    stereo = OutputDeviceInfo(
        index=0,
        name="Headphones",
        max_output_channels=2,
        default_samplerate=48000.0,
        hostapi_name="Test",
    )
    monkeypatch.setattr(eng_mod, "list_output_devices", lambda dedupe=True: [stereo])
    monkeypatch.setattr(eng_mod.sd, "check_output_settings", lambda **kwargs: None)

    assert FIXTURE.is_file()
    buf = load_audio(FIXTURE)
    song = Song.create("Opening")
    song.use_left_ltc = True

    engine = eng_mod.AudioEngine()
    engine.apply_audio_settings(
        AudioOutputSettings(
            output_device_name="Headphones",
            music_l_route="1",
            music_r_route="2",
            ltc_enabled=True,
            ltc_source="generator",
            ltc_generator_enabled=True,
            ltc_channels=[2],  # clamps to CH2 on 2-out device
        )
    )
    engine.set_song(song)
    engine.set_buffer(buf)
    engine.flush_deferred_buffer_setup()
    engine.refresh_song_ltc_routing()

    assert engine._route.get(2) == [1]  # LTC → CH2 only
    music_dests = set(engine._route.get(3) or []) | set(engine._route.get(0) or []) | set(
        engine._route.get(1) or []
    )
    assert 1 not in music_dests  # music must not share LTC CH2
    assert 0 in music_dests

