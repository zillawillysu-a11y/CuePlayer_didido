"""BPM re-detect respects manual values; Sheet progress clears after detect."""

from __future__ import annotations

import os
import uuid

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from cueplayer.domain.models import AudioTrack, Project
from cueplayer.ui.main_window import MainWindow
from cueplayer.ui.setlist_sheet_page import SetlistSheetPage, _COL_BPM


@pytest.fixture
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _main_track(path: Path) -> AudioTrack:
    return AudioTrack(
        id=str(uuid.uuid4()),
        name="Main",
        path=path,
        role="main",
    )


def test_force_redetect_skips_manual_bpm(
    app: QApplication, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    wav = tmp_path / "a.wav"
    wav.write_bytes(b"RIFF")

    project = Project.create("BPM Manual")
    song = project.new_song("Manual")
    song.bpm = 135.0
    song.bpm_auto = False
    song.audio_tracks = [_main_track(wav)]
    project.songs = [song]

    monkeypatch.setattr(MainWindow, "_confirm_discard_if_dirty", lambda self: True)
    window = MainWindow(project=project)

    assert window._schedule_bpm_detect_for_song(song, force=True) is False
    assert song.bpm == 135.0
    assert song.bpm_auto is False


def test_force_redetect_allows_auto_bpm(
    app: QApplication, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    wav = tmp_path / "b.wav"
    wav.write_bytes(b"RIFF")

    project = Project.create("BPM Auto")
    song = project.new_song("Auto")
    song.bpm = 190.0
    song.bpm_auto = True
    song.audio_tracks = [_main_track(wav)]
    project.songs = [song]

    monkeypatch.setattr(MainWindow, "_confirm_discard_if_dirty", lambda self: True)
    window = MainWindow(project=project)
    monkeypatch.setattr(window, "_pump_bpm_detect_queue", lambda: None)

    assert window._schedule_bpm_detect_for_song(song, force=True) is True
    assert song.id in window._bpm_detect_inflight


def test_sheet_clear_bpm_progress_restores_value(app: QApplication) -> None:
    project = Project.create("Sheet BPM")
    song = project.new_song("Song")
    song.bpm = 96.0
    song.bpm_auto = True
    project.songs = [song]

    page = SetlistSheetPage()
    page.set_project(project)
    page.sync_songs()
    page.set_song_bpm_progress(song.id, 100)
    row = page._song_ids.index(song.id)
    assert page.table.item(row, _COL_BPM).text().endswith("%")

    page.clear_song_bpm_progress(song.id)
    assert page.table.item(row, _COL_BPM).text() == "<96>"
    assert song.id not in page._bpm_progress
