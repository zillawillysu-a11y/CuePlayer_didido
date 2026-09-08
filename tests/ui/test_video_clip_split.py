"""Split Video Clip at Playhead: no-op boundaries, selection, and persistence."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from cueplayer.domain.models import LtcClip, Mark, Project, VideoClip
from cueplayer.persistence.project_store import load_project, save_project
from cueplayer.ui.main_window import MainWindow


@pytest.fixture
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _new_window() -> MainWindow:
    return MainWindow(Project.create("Split Test"))


def _song_with_one_clip(window: MainWindow) -> VideoClip:
    song = window.current_song
    song.video_clips = []
    clip = VideoClip.create(
        name="a", path=Path("does-not-exist.mp4"), start_seconds=10.0, source_in_seconds=5.0, duration_seconds=20.0
    )
    song.add_video_clip(clip)
    return clip


def test_split_no_selected_clip_is_noop(app: QApplication) -> None:
    # TEST S4
    window = _new_window()
    clip = _song_with_one_clip(window)
    before = len(window.current_song.video_clips)
    window._split_video_clip("not-a-real-id", 18.0)
    assert len(window.current_song.video_clips) == before


def test_split_playhead_outside_clip_is_noop(app: QApplication) -> None:
    # TEST S5
    window = _new_window()
    clip = _song_with_one_clip(window)
    window._split_video_clip(clip.id, 5.0)  # before clip.start_seconds
    assert len(window.current_song.video_clips) == 1
    window._split_video_clip(clip.id, 35.0)  # after clip.end_seconds
    assert len(window.current_song.video_clips) == 1


def test_split_invalid_boundary_is_noop(app: QApplication) -> None:
    # TEST S3 (UI level): exactly at clip start/end never splits.
    window = _new_window()
    clip = _song_with_one_clip(window)
    window._split_video_clip(clip.id, clip.start_seconds)
    window._split_video_clip(clip.id, clip.end_seconds)
    assert len(window.current_song.video_clips) == 1


def test_split_selects_right_clip(app: QApplication) -> None:
    # TEST S7: right clip becomes selected after split.
    window = _new_window()
    clip = _song_with_one_clip(window)
    window._split_video_clip(clip.id, 18.0)
    clips = sorted(window.current_song.video_clips, key=lambda c: c.start_seconds)
    assert len(clips) == 2
    left, right = clips
    assert left.id == clip.id
    assert right.start_seconds == pytest.approx(18.0)
    assert window.timeline._selected_clip_ids == {right.id}


def test_split_undo_redo_is_single_step(app: QApplication) -> None:
    # TEST S6 through the MainWindow undo stack.
    window = _new_window()
    clip = _song_with_one_clip(window)
    window._split_video_clip(clip.id, 18.0)
    assert len(window.current_song.video_clips) == 2

    window._undo_action()
    assert len(window.current_song.video_clips) == 1
    assert window.current_song.video_clips[0].start_seconds == pytest.approx(10.0)
    assert window.current_song.video_clips[0].duration_seconds == pytest.approx(20.0)

    window._redo_action()
    assert len(window.current_song.video_clips) == 2


def test_split_does_not_touch_other_objects(app: QApplication) -> None:
    # TEST S9
    window = _new_window()
    clip = _song_with_one_clip(window)
    other_clip = VideoClip.create(name="b", path=Path("other.mp4"), start_seconds=100.0, duration_seconds=5.0)
    window.current_song.add_video_clip(other_clip)
    mark = Mark.create(1, 3.0)
    window.current_song.marks.append(mark)
    ltc = LtcClip.create(timeline_start_seconds=50.0, duration_seconds=5.0, start_timecode="01:00:00:00")
    window.current_song.ltc_clips.append(ltc)

    window._split_video_clip(clip.id, 18.0)

    assert window.current_song.video_clip_by_id(other_clip.id).start_seconds == pytest.approx(100.0)
    assert window.current_song.marks[0].time_seconds == pytest.approx(3.0)
    assert window.current_song.ltc_clips[0].timeline_start_seconds == pytest.approx(50.0)


def test_split_persists_across_save_reload(app: QApplication, tmp_path: Path) -> None:
    # TEST S8
    window = _new_window()
    clip = _song_with_one_clip(window)
    window._split_video_clip(clip.id, 18.0)
    clips = sorted(window.current_song.video_clips, key=lambda c: c.start_seconds)
    assert len(clips) == 2

    project_path = tmp_path / "split_project.cueplayer"
    save_project(window.project, project_path)
    reloaded = load_project(project_path)
    reloaded_song = reloaded.songs[0]
    reloaded_clips = sorted(reloaded_song.video_clips, key=lambda c: c.start_seconds)
    assert len(reloaded_clips) == 2
    for original, restored in zip(clips, reloaded_clips):
        assert restored.id == original.id
        assert restored.start_seconds == pytest.approx(original.start_seconds)
        assert restored.source_in_seconds == pytest.approx(original.source_in_seconds)
        assert restored.duration_seconds == pytest.approx(original.duration_seconds)
        assert restored.path.name == original.path.name
