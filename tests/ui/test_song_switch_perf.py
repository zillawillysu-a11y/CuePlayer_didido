"""Song switch should stay responsive (no sync disk I/O or full-setlist work)."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from cueplayer.domain.models import AudioTrack, Project
from cueplayer.media.audio_loader import AudioBuffer
from cueplayer.ui.main_window import MainWindow


@pytest.fixture
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _make_window_with_songs(app: QApplication, n: int = 5) -> MainWindow:
    project = Project.create("Perf")
    for i in range(n):
        song = project.new_song(f"Song {i + 1}")
        song.audio_tracks = [
            AudioTrack(
                id="main",
                name=f"s{i}",
                path=Path(f"/fake/song{i}.wav"),
                role="main",
            )
        ]
        project.songs.append(song)
    window = MainWindow(project)
    window.show()
    app.processEvents()
    return window


def test_cached_audio_buffer_is_ram_only(app: QApplication) -> None:
    window = _make_window_with_songs(app, n=1)
    path = Path("/fake/song0.wav")
    key = (str(path.resolve()), 1, 100)
    buffer = AudioBuffer(
        path=path,
        sample_rate=48000,
        samples=__import__("numpy").zeros((10, 2), dtype="float32"),
        mono=__import__("numpy").zeros(10, dtype="float32"),
        peak_levels=[],
    )
    with patch.object(window, "_audio_cache_key", return_value=key):
        assert window._cached_audio_buffer(path) is None
        window._audio_buffer_cache[key] = buffer
        assert window._cached_audio_buffer(path) is buffer


def test_prefetch_neighbor_audio_only_schedules_neighbors(app: QApplication) -> None:
    window = _make_window_with_songs(app, n=5)
    paths = [Path(f"/fake/song{i}.wav") for i in range(5)]

    def _path_for_song(song):  # noqa: ANN001
        try:
            idx = window.project.songs.index(song)
        except ValueError:
            return None
        return paths[idx]

    window._activate_song(2, stop_playback=False)
    scheduled: list[Path] = []

    def _capture(path: Path, *, executor) -> MagicMock:  # noqa: ANN001
        scheduled.append(Path(path))
        fut = MagicMock()
        fut.done.return_value = False
        return fut

    with patch.object(window, "_main_audio_path_for_song", side_effect=_path_for_song):
        with patch.object(window, "_start_audio_load", side_effect=_capture):
            window._prefetch_neighbor_audio(skip_path=paths[2])

    assert scheduled == [paths[1], paths[3]]


def test_on_bpm_detected_updates_one_cell_not_full_rebuild(app: QApplication) -> None:
    window = _make_window_with_songs(app, n=3)
    window._rebuild_song_list(select_indexes=[0])
    song = window.project.songs[1]
    song_id = song.id
    window._bpm_force_ids.add(song_id)

    with patch.object(window, "_rebuild_song_list") as rebuild:
        with patch.object(window, "_refresh_bpm_progress_cell") as refresh_cell:
            window._on_bpm_detected(song_id, 128.0)

    rebuild.assert_not_called()
    refresh_cell.assert_called_once_with(song_id)
    assert song.bpm == 128.0
    assert song.bpm_auto is True


def test_apply_loaded_audio_skips_playback_ready_on_song_switch(app: QApplication) -> None:
    window = _make_window_with_songs(app, n=1)
    path = Path("/fake/song0.wav")
    buffer = AudioBuffer(
        path=path,
        sample_rate=48000,
        samples=__import__("numpy").zeros((4800, 2), dtype="float32"),
        mono=__import__("numpy").zeros(4800, dtype="float32"),
        peak_levels=[],
    )
    with patch.object(window.engine, "ensure_playback_ready") as ready:
        window._apply_loaded_audio(
            buffer,
            path,
            mark_dirty=False,
            replace_track=False,
            refresh_song_widgets=False,
        )
    ready.assert_not_called()
