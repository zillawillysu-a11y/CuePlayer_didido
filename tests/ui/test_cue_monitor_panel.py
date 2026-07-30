"""Tests for cue monitor NOW body and labels."""

from __future__ import annotations

from cueplayer.domain.models import Mark, Song
from cueplayer.ui.cue_monitor_panel import mark_now_body


def test_mark_now_body_type_above_note() -> None:
    song = Song.create("Test")
    mark = Mark.create(lane_index=1, time_seconds=1.0, display_name="Verse")
    assert mark_now_body(song, mark) == "Main\n-\nVerse"


def test_mark_now_body_shows_cue_id_on_primary() -> None:
    song = Song.create("Test")
    mark = song.add_mark(1, 1.0)
    assert mark.main_cue_id == "1"
    assert mark_now_body(song, mark, show_cue_id=True) == "Main\n-\nCue 1"


def test_mark_now_body_primary_cue_id_with_note() -> None:
    song = Song.create("Test")
    mark = song.add_mark(1, 1.0, display_name="Chorus")
    mark.main_cue_id = "3"
    assert mark_now_body(song, mark, show_cue_id=True) == "Main\n-\nCue 3\nChorus"


def test_mark_now_body_hides_cue_id_when_disabled() -> None:
    song = Song.create("Test")
    mark = song.add_mark(1, 1.0, display_name="Verse")
    assert mark.main_cue_id == "1"
    assert mark_now_body(song, mark, show_cue_id=False) == "Main\n-\nVerse"


def test_mark_now_body_type_only_when_note_empty() -> None:
    song = Song.create("Test")
    mark = Mark.create(lane_index=1, time_seconds=1.0, display_name="")
    assert mark_now_body(song, mark) == "Main"
