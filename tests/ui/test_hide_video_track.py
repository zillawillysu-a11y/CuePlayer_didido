"""Hide / show Video track lane (post-alignment chrome collapse)."""

from __future__ import annotations

import json
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


def test_show_video_track_persists_project_global(tmp_path: Path) -> None:
    project = Project.create("Show")
    project.set_show_video_track(False)
    path = tmp_path / "中文" / "show.cueplayer.json"
    save_project(project, path)
    loaded = load_project(path)
    assert loaded.show_video_track is False
    assert loaded.songs[0].show_video_track is False
    assert loaded.songs[0].show_ltc_track is False


def test_show_video_track_defaults_true_for_legacy(tmp_path: Path) -> None:
    project = Project.create("Legacy")
    path = tmp_path / "show.cueplayer.json"
    save_project(project, path)
    data = json.loads(path.read_text(encoding="utf-8"))
    data.pop("show_video_track", None)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    loaded = load_project(path)
    assert loaded.show_video_track is True
    assert loaded.songs[0].show_video_track is True


def test_legacy_project_inherits_eye_from_first_song(tmp_path: Path) -> None:
    project = Project.create("Legacy Eye")
    path = tmp_path / "legacy_eye.cueplayer.json"
    save_project(project, path)
    data = json.loads(path.read_text(encoding="utf-8"))
    data.pop("show_video_track", None)
    data["songs"][0]["show_video_track"] = False
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    loaded = load_project(path)
    assert loaded.show_video_track is False
    assert all(s.show_video_track is False for s in loaded.songs)


def test_hide_video_track_collapses_lane(app: QApplication) -> None:
    widget = TimelineWidget()
    song = _song_with_clip()
    widget.set_song(song)
    widget.resize(900, 600)
    assert widget._video_lane_visible() is True
    before_height = widget._content_height
    marks_top = widget._tracks_top_y()
    wave_bottom = widget._wave_bottom_y()
    eye_pos = widget.video_show_button.pos()

    events: list[bool] = []
    widget.video_track_visibility_changed.connect(events.append)
    widget.set_show_video_track(False)

    assert song.show_video_track is False
    assert widget._video_lane_visible() is False
    assert widget._video_eye_header_visible() is True
    # Marks stay glued under Music whether Video is shown or hidden.
    assert widget._tracks_top_y() == wave_bottom == marks_top
    assert widget._content_height < before_height
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
    widget.set_song(song)
    widget.set_show_video_track(False)
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


def test_eye_stays_global_across_song_switch(app: QApplication) -> None:
    widget = TimelineWidget()
    a = _song_with_clip()
    a.name = "Song A"
    b = _song_with_clip()
    b.name = "Song B"
    b.show_video_track = False  # ignored — eye is global on the widget/project
    widget.set_song(a)
    widget.resize(900, 600)
    widget.set_show_video_track(False)
    assert widget._video_lane_visible() is False

    widget.set_song(b)
    assert widget._show_video_track is False
    assert widget._video_lane_visible() is False
    assert b.show_video_track is False

    widget.set_show_video_track(True)
    widget.set_song(a)
    assert widget._video_lane_visible() is True
    assert a.show_video_track is True


def test_project_set_show_video_track_syncs_all_songs() -> None:
    project = Project.create("Jam")
    project.songs.append(project.new_song("第二首"))
    project.set_show_video_track(False)
    assert project.show_video_track is False
    assert all(s.show_video_track is False and s.show_ltc_track is False for s in project.songs)
    third = project.new_song("第三首")
    project.songs.append(third)
    assert third.show_video_track is False
