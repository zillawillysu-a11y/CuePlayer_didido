"""Tests for cue monitor NOW body and labels."""

from __future__ import annotations

from cueplayer.domain.models import Mark, Song
from cueplayer.ui.cue_monitor_panel import mark_now_body


def test_mark_now_body_type_above_note() -> None:
    song = Song.create("Test")
    mark = Mark.create(lane_index=1, time_seconds=1.0, display_name="Verse")
    assert mark_now_body(song, mark) == "Main\nVerse"


def test_mark_now_body_type_only_when_note_empty() -> None:
    song = Song.create("Test")
    mark = Mark.create(lane_index=1, time_seconds=1.0, display_name="")
    assert mark_now_body(song, mark) == "Main"
