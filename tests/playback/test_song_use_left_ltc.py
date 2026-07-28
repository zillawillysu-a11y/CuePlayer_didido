"""Per-song File LTC (Left/Right/Auto) routes stripe to settings LTC channel."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication, QComboBox

from cueplayer.domain.models import AudioOutputSettings, AudioTrack, Project, Song
from cueplayer.media.audio_loader import load_audio
from cueplayer.persistence.project_store import project_from_dict, project_to_dict
from cueplayer.playback import audio_engine as eng_mod
from cueplayer.playback.devices import OutputDeviceInfo
from cueplayer.ui.song_edit_dialog import SongDraft, SongEditDialog

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "fixtures" / "media" / "中文測試" / "LTC左_音樂右_測試.wav"


def _device(channels: int = 8) -> OutputDeviceInfo:
    return OutputDeviceInfo(
        index=0,
        name="Test",
        max_output_channels=channels,
        default_samplerate=48000.0,
        hostapi_name="Test",
    )


@pytest.fixture
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_song_edit_dialog_has_file_ltc_combo(app: QApplication) -> None:
    dialog = SongEditDialog(
        [SongDraft(name="Opening", setlist_number=1.0, file_ltc_side="right")],
        title="Edit Song",
    )
    from cueplayer.ui import song_edit_dialog as sed

    combo = dialog.table.cellWidget(0, sed._COL_LEFT_LTC)
    assert isinstance(combo, QComboBox)
    assert combo.currentData() == "right"


def test_file_ltc_side_persists_and_migrates_legacy() -> None:
    project = Project.create("LTC Flag")
    project.songs[0].file_ltc_side = "right"
    restored = project_from_dict(project_to_dict(project))
    assert restored.songs[0].file_ltc_side == "right"

    legacy = project_to_dict(project)
    legacy["songs"][0].pop("file_ltc_side", None)
    legacy["songs"][0]["use_left_ltc"] = True
    migrated = project_from_dict(legacy)
    assert migrated.songs[0].file_ltc_side == "left"


def test_file_ltc_right_strips_right_from_music(monkeypatch, app: QApplication) -> None:
    monkeypatch.setattr(eng_mod, "list_output_devices", lambda dedupe=True: [_device()])
    monkeypatch.setattr(eng_mod.sd, "check_output_settings", lambda **kwargs: None)

    assert FIXTURE.is_file()
    buf = load_audio(FIXTURE)
    # Swap so LTC is on Right for this test.
    swapped = buf.samples.copy()
    swapped[:, 0], swapped[:, 1] = buf.samples[:, 1].copy(), buf.samples[:, 0].copy()
    from cueplayer.media.audio_loader import AudioBuffer, build_peak_pyramid

    mono, levels = build_peak_pyramid(swapped, buf.sample_rate)
    right_ltc = AudioBuffer(
        path=buf.path,
        sample_rate=buf.sample_rate,
        samples=swapped,
        mono=mono,
        peak_levels=levels,
    )

    song = Song.create("Stripe R")
    song.file_ltc_side = "right"
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
    engine.set_buffer(right_ltc)
    engine.flush_deferred_buffer_setup()
    engine.refresh_song_ltc_routing()

    assert engine._effective_ltc_source_channel() == 1
    assert engine._cached_music_indices == (0, 0)  # Left music only
    music = engine._music_chunk(0, 2048, engine._sample_rate())
    ltc = engine._ltc_chunk(0, 2048)
    assert np.any(ltc != 0.0)
    assert np.any(music != 0.0)
    assert engine._route.get(2) == [2]
    assert 2 not in (engine._route.get(3) or [])


def test_song_use_left_ltc_routes_left_to_ltc_bus(monkeypatch, app: QApplication) -> None:
    monkeypatch.setattr(eng_mod, "list_output_devices", lambda dedupe=True: [_device()])
    monkeypatch.setattr(eng_mod.sd, "check_output_settings", lambda **kwargs: None)

    assert FIXTURE.is_file()
    buf = load_audio(FIXTURE)
    song = Song.create("Opening")
    song.file_ltc_side = "left"
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
    assert engine._route.get(2) == [2]
    assert engine._route.get(3) == [0, 1]
    assert engine._cached_music_indices == (1, 1)
