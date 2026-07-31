"""Song switch: disk cache instant path, no background prefetch storm."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
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
    """Song switch must not sync-load .npz on the UI thread."""
    window = _make_window_with_songs(app, n=1)
    path = Path("/fake/song0.wav")
    key = ("resolved", 1, 100)
    buffer = AudioBuffer(
        path=path,
        sample_rate=48000,
        samples=np.zeros((10, 2), dtype=np.float32),
        mono=np.zeros(10, dtype=np.float32),
        peak_levels=[],
    )
    with patch.object(window, "_audio_cache_key", return_value=key):
        with patch(
            "cueplayer.media.audio_disk_cache.load_cached_audio", return_value=buffer
        ) as load_disk:
            miss = window._cached_audio_buffer(path)
            assert miss is None
            load_disk.assert_not_called()
            window._audio_buffer_cache[key] = buffer
            hit = window._cached_audio_buffer(path)
    assert hit is buffer


def test_activate_song_defers_monitor_rebuild(app: QApplication) -> None:
    window = _make_window_with_songs(app, n=2)
    with patch.object(window, "_cached_audio_buffer", return_value=MagicMock()):
        with patch.object(window.monitor, "set_song") as set_song:
            window._activate_song(1, stop_playback=True)
            set_song.assert_not_called()
            app.processEvents()
            set_song.assert_called_once_with(window.current_song)


def test_activate_song_does_not_prefetch_neighbors(app: QApplication) -> None:
    window = _make_window_with_songs(app, n=3)
    paths = [Path(f"/fake/song{i}.wav") for i in range(3)]

    def _path_for_song(song):  # noqa: ANN001
        return paths[window.project.songs.index(song)]

    with patch.object(window, "_main_audio_path_for_song", side_effect=_path_for_song):
        with patch.object(window, "_cached_audio_buffer", return_value=MagicMock()):
            with patch.object(window, "_prefetch_neighbor_audio") as prefetch:
                window._activate_song(1, stop_playback=False)
    prefetch.assert_not_called()


def test_activate_song_quiesces_output(app: QApplication) -> None:
    window = _make_window_with_songs(app, n=2)
    with patch.object(window, "_cached_audio_buffer", return_value=MagicMock()):
        with patch.object(window.engine, "quiesce_output") as quiesce:
            window._activate_song(1, stop_playback=True)
    quiesce.assert_called_once()


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
        samples=np.zeros((4800, 2), dtype=np.float32),
        mono=np.zeros(4800, dtype=np.float32),
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
