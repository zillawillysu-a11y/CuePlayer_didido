"""Hide / show Video track lane (post-alignment chrome collapse)."""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from cueplayer.domain.models import Project, Song, VideoClip
from cueplayer.persistence.project_store import load_project, save_project
from cueplayer.ui.timeline_widget import TimelineWidget


@pytest.fixture
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _song_with_clip() -> Song:
    song = Song.create("對齊完成")
    song.add_video_clip(
        VideoClip.create(name="vj", path=Path("a.mp4"), start_seconds=0.0, duration_seconds=2.0)
    )
    return song


def test_show_video_track_persists(tmp_path: Path) -> None:
    project = Project.create("Show")
    project.songs[0].show_video_track = False
    path = tmp_path / "中文" / "show.cueplayer.json"
    save_project(project, path)
    loaded = load_project(path)
    assert loaded.songs[0].show_video_track is False


def test_show_video_track_defaults_true_for_legacy(tmp_path: Path) -> None:
    project = Project.create("Legacy")
    path = tmp_path / "show.cueplayer.json"
    save_project(project, path)
    text = path.read_text(encoding="utf-8").replace('"show_video_track": true,\n', "", 1)
    path.write_text(text, encoding="utf-8")
    loaded = load_project(path)
    assert loaded.songs[0].show_video_track is True


def test_hide_video_track_collapses_lane(app: QApplication) -> None:
    widget = TimelineWidget()
    song = _song_with_clip()
    widget.set_song(song)
    widget.resize(900, 600)
    assert widget._video_lane_visible() is True
    before_tracks = widget._tracks_top_y()
    wave_bottom = widget._wave_bottom_y()
    eye_pos = widget.video_show_button.pos()

    events: list[bool] = []
    widget.video_track_visibility_changed.connect(events.append)
    widget.set_show_video_track(False)

    assert song.show_video_track is False
    assert widget._video_lane_visible() is False
    assert widget._video_eye_header_visible() is True
    assert widget._tracks_top_y() == wave_bottom
    assert widget._tracks_top_y() < before_tracks
    assert events == [False]
    assert widget.video_mute_button.isHidden() is True
    assert widget.video_hide_button.isHidden() is True
    assert widget.video_show_button.isHidden() is False
    assert widget.video_show_button.pos() == eye_pos


def test_hide_button_hides_track(app: QApplication) -> None:
    widget = TimelineWidget()
    song = _song_with_clip()
    widget.set_song(song)
    widget.resize(900, 600)
    widget.video_hide_button.click()
    assert song.show_video_track is False
    assert widget._video_lane_visible() is False
    assert widget.video_show_button.isHidden() is False


def test_show_eye_button_restores_track(app: QApplication) -> None:
    widget = TimelineWidget()
    song = _song_with_clip()
    song.show_video_track = False
    widget.set_song(song)
    widget.resize(900, 600)
    assert widget.video_show_button.isHidden() is False
    eye_pos = widget.video_show_button.pos()
    widget.video_show_button.click()
    assert song.show_video_track is True
    assert widget._video_lane_visible() is True
    # Eye stays put on the Music header — icon flips to eye_off instead of moving.
    assert widget.video_show_button.isHidden() is False
    assert widget.video_show_button.pos() == eye_pos
    assert widget.video_show_button._kind == "eye_off"
    assert widget.video_hide_button.isHidden() is True
    widget.video_show_button.click()
    assert song.show_video_track is False
    assert widget.video_show_button.pos() == eye_pos
    assert widget.video_show_button._kind == "eye"


def test_set_song_restores_hidden_video_track(app: QApplication) -> None:
    widget = TimelineWidget()
    song = _song_with_clip()
    song.show_video_track = False
    widget.set_song(song)
    assert widget._show_video_track is False
    assert widget._video_lane_visible() is False
    assert widget._video_eye_header_visible() is True
    assert widget.video_show_button.isHidden() is False
