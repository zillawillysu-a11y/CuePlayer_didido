"""Video track header chrome: Mute toggle + the expandable per-clip volume
fader (see AGENTS.md — video audio / video track mute feedback)."""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from cueplayer.domain.models import Song, VideoClip
from cueplayer.ui.timeline_widget import TimelineWidget


@pytest.fixture
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _song_with_clip(volume: float = 1.0) -> tuple[Song, VideoClip]:
    song = Song.create("Song")
    clip = VideoClip.create(name="clip", path=Path("clip.mp4"), start_seconds=0.0, duration_seconds=2.0, volume=volume)
    song.add_video_clip(clip)
    return song, clip


def test_mute_button_toggle_emits_signal_and_updates_state(app: QApplication) -> None:
    widget = TimelineWidget()
    song, _clip = _song_with_clip()
    widget.set_song(song)

    events: list[bool] = []
    widget.video_track_mute_toggled.connect(events.append)

    assert widget._video_track_muted is False
    widget.video_mute_button.click()
    assert widget._video_track_muted is True
    assert events == [True]

    widget.video_mute_button.click()
    assert widget._video_track_muted is False
    assert events == [True, False]


def test_set_song_syncs_mute_button_from_song_state(app: QApplication) -> None:
    widget = TimelineWidget()
    song, _clip = _song_with_clip()
    song.video_track_muted = True

    widget.set_song(song)
    assert widget._video_track_muted is True
    assert widget.video_mute_button._active is True


def test_selecting_single_clip_syncs_volume_slider(app: QApplication) -> None:
    widget = TimelineWidget()
    song, clip = _song_with_clip(volume=0.6)
    widget.set_song(song)

    widget.set_selected_video_clip_ids([clip.id])
    assert widget.video_clip_volume_slider.value() == 60
    assert widget.video_clip_volume_slider.isEnabled() is True


def test_no_selection_disables_volume_slider(app: QApplication) -> None:
    widget = TimelineWidget()
    song, _clip = _song_with_clip()
    widget.set_song(song)

    widget.set_selected_video_clip_ids([])
    assert widget.video_clip_volume_slider.isEnabled() is False


def test_multi_selection_disables_volume_slider(app: QApplication) -> None:
    widget = TimelineWidget()
    song = Song.create("Song")
    a = VideoClip.create(name="a", path=Path("a.mp4"), start_seconds=0.0, duration_seconds=2.0)
    b = VideoClip.create(name="b", path=Path("b.mp4"), start_seconds=5.0, duration_seconds=2.0)
    song.add_video_clip(a)
    song.add_video_clip(b)
    widget.set_song(song)

    widget.set_selected_video_clip_ids([a.id, b.id])
    assert widget.video_clip_volume_slider.isEnabled() is False


def test_dragging_volume_slider_updates_clip_and_emits_signal(app: QApplication) -> None:
    widget = TimelineWidget()
    song, clip = _song_with_clip(volume=1.0)
    widget.set_song(song)
    widget.set_selected_video_clip_ids([clip.id])

    changes: list[tuple[str, float]] = []
    widget.video_clip_volume_changed.connect(lambda cid, vol: changes.append((cid, vol)))

    widget.video_clip_volume_slider.setValue(35)

    assert clip.volume == pytest.approx(0.35)
    assert changes == [(clip.id, pytest.approx(0.35))]


def test_expand_toggle_shows_and_hides_volume_slider(app: QApplication) -> None:
    widget = TimelineWidget()
    song, clip = _song_with_clip()
    widget.set_song(song)
    widget.set_selected_video_clip_ids([clip.id])
    widget.resize(900, 600)

    # The widget hierarchy isn't shown in this test, so check the slider's
    # own hidden flag (isVisible() also depends on ancestor visibility).
    assert widget.video_clip_volume_slider.isHidden() is True
    widget.video_expand_button.click()
    assert widget._video_track_expanded is True
    assert widget.video_clip_volume_slider.isHidden() is False

    widget.video_expand_button.click()
    assert widget._video_track_expanded is False
    assert widget.video_clip_volume_slider.isHidden() is True


def test_expanding_grows_video_lane_height(app: QApplication) -> None:
    widget = TimelineWidget()
    song, _clip = _song_with_clip()
    widget.set_song(song)

    collapsed_height = widget._video_lane_height
    widget.video_expand_button.click()
    assert widget._video_lane_height == pytest.approx(collapsed_height + widget._video_expand_extra)


def test_expand_toggle_shows_music_volume_alongside_video_volume(app: QApplication) -> None:
    """Expanding Video track chrome must reveal Music volume too (同步顯示),
    not just the per-clip Video volume — see AGENTS.md alignment-balance note."""
    widget = TimelineWidget()
    song, clip = _song_with_clip()
    widget.set_song(song)
    widget.set_selected_video_clip_ids([clip.id])
    widget.resize(900, 600)

    assert widget.music_volume_slider.isHidden() is True
    widget.video_expand_button.click()
    assert widget.video_clip_volume_slider.isHidden() is False
    assert widget.music_volume_slider.isHidden() is False

    widget.video_expand_button.click()
    assert widget.video_clip_volume_slider.isHidden() is True
    assert widget.music_volume_slider.isHidden() is True


def test_set_song_syncs_music_volume_slider_from_song_state(app: QApplication) -> None:
    widget = TimelineWidget()
    song, _clip = _song_with_clip()
    song.music_volume = 0.7

    widget.set_song(song)
    assert widget.music_volume_slider.value() == 70


def test_dragging_music_volume_slider_updates_song_and_emits_signal(app: QApplication) -> None:
    widget = TimelineWidget()
    song, _clip = _song_with_clip()
    widget.set_song(song)

    changes: list[float] = []
    widget.music_volume_changed.connect(changes.append)

    widget.music_volume_slider.setValue(55)

    assert song.music_volume == pytest.approx(0.55)
    assert changes == [pytest.approx(0.55)]


def test_set_song_loads_persisted_video_lane_height(app: QApplication) -> None:
    widget = TimelineWidget()
    widget.resize(900, 600)
    song, _clip = _song_with_clip()
    song.video_lane_height = 72.0
    widget.set_song(song)
    assert widget._video_lane_base_height == pytest.approx(72.0)


def test_set_video_lane_height_updates_song_and_layout(app: QApplication) -> None:
    widget = TimelineWidget()
    song, _clip = _song_with_clip()
    widget.set_song(song)
    widget.resize(900, 600)

    widget.set_video_lane_height(88.0)

    assert song.video_lane_height == pytest.approx(88.0)
    assert widget._video_lane_base_height == pytest.approx(88.0)
    assert widget._video_lane_height == pytest.approx(88.0)


def test_video_lane_height_clamps_to_min_and_max(app: QApplication) -> None:
    widget = TimelineWidget()
    song, _clip = _song_with_clip()
    widget.set_song(song)
    widget.resize(900, 600)

    widget.set_video_lane_height(10.0)
    assert widget._video_lane_base_height == pytest.approx(widget._video_lane_min_height)

    max_h = widget._max_video_lane_height()
    widget.set_video_lane_height(999.0)
    assert widget._video_lane_base_height == pytest.approx(max_h)
    assert max_h > widget._video_lane_min_height
