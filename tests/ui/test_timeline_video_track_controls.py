"""Video track header chrome: Mute toggle + always-visible per-clip volume
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
    clip = VideoClip.create(
        name="clip",
        path=Path("clip.mp4"),
        start_seconds=0.0,
        duration_seconds=2.0,
        volume=volume,
    )
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


def test_video_volume_slider_always_visible_without_expand(app: QApplication) -> None:
    widget = TimelineWidget()
    song, clip = _song_with_clip()
    widget.set_song(song)
    widget.set_selected_video_clip_ids([clip.id])
    widget.resize(900, 600)
    widget._layout_video_track_overlay()

    assert not hasattr(widget, "video_expand_button")
    assert widget.video_clip_volume_slider.isHidden() is False
    assert widget._video_lane_height == pytest.approx(
        widget._video_lane_base_height + widget._video_volume_row_height
    )


def test_music_volume_independent_of_video_volume_row(app: QApplication) -> None:
    """Music bed volume lives in the Music header expand; Video volume is always shown."""
    widget = TimelineWidget()
    song, clip = _song_with_clip()
    widget.set_song(song)
    widget.set_selected_video_clip_ids([clip.id])
    widget.resize(900, 600)
    widget._layout_video_track_overlay()

    assert widget.music_volume_slider.isHidden() is True
    assert widget.video_clip_volume_slider.isHidden() is False

    widget.music_expand_button.click()
    assert widget.music_volume_slider.isHidden() is False
    assert widget.audio_gain_slider.isHidden() is False
    assert widget.video_clip_volume_slider.isHidden() is False

    widget.music_expand_button.click()
    assert widget.music_volume_slider.isHidden() is True
    assert widget.video_clip_volume_slider.isHidden() is False


def test_music_volume_available_without_video_eye(app: QApplication) -> None:
    widget = TimelineWidget()
    song, _clip = _song_with_clip()
    widget.set_song(song)
    widget.resize(900, 600)
    widget.set_show_video_track(False)

    widget.music_expand_button.click()
    assert widget._music_header_expanded is True
    assert widget.music_volume_slider.isHidden() is False
    assert widget.video_clip_volume_slider.isHidden() is True


def test_music_header_expand_grows_layout_height(app: QApplication) -> None:
    widget = TimelineWidget()
    song, _clip = _song_with_clip()
    widget.set_song(song)
    widget.resize(900, 600)

    collapsed = widget._content_height
    widget.music_expand_button.click()
    assert widget._content_height == collapsed + int(widget._music_expand_extra)


def test_dragging_audio_gain_slider_updates_song_and_emits_signal(app: QApplication) -> None:
    widget = TimelineWidget()
    song, _clip = _song_with_clip()
    widget.set_song(song)

    changes: list[float] = []
    widget.audio_gain_changed.connect(changes.append)

    widget.audio_gain_slider.setValue(35)

    assert song.audio_gain_db == pytest.approx(3.5, abs=0.05)
    assert changes == [pytest.approx(3.5, abs=0.05)]


def test_set_song_syncs_audio_gain_slider_from_song_state(app: QApplication) -> None:
    widget = TimelineWidget()
    song, _clip = _song_with_clip()
    song.audio_gain_db = -4.5

    widget.set_song(song)
    assert widget.audio_gain_slider.value() == -45
    assert widget.audio_gain_label.text() == "-4.5 dB"


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
    widget.music_expand_button.click()

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
    assert widget._video_lane_height == pytest.approx(88.0 + widget._video_volume_row_height)


def test_video_lane_height_clamps_to_min_and_max(app: QApplication) -> None:
    widget = TimelineWidget()
    song, _clip = _song_with_clip()
    widget.set_song(song)
    widget.resize(900, 600)

    widget.set_video_lane_height(10.0)
    assert widget._video_lane_base_height == pytest.approx(widget._video_lane_min_height)

    max_h = widget._max_video_lane_height()
    widget.set_video_lane_height(max_h + 500.0)
    assert widget._video_lane_base_height == pytest.approx(max_h)
    assert max_h > widget._video_lane_min_height
