"""Align Anchors beta — PlaybackService preview lifecycle regression tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from cueplayer.application.playback_service import PlaybackService
from cueplayer.domain.models import Song
from cueplayer.domain.song_session import SongSession
from cueplayer.domain.song_variant import SongVariant
from cueplayer.domain.undo import SetVariantAnchorOffsetCommand, UndoStack

from tests.application.test_playback_service import _FakeEngine


def _svc_with_variant(
    tmp_path: Path, *, anchor_offset: float = 0.0
) -> tuple[PlaybackService, _FakeEngine, Song, SongVariant]:
    session = SongSession()
    engine = _FakeEngine()
    svc = PlaybackService(engine, session)  # type: ignore[arg-type]
    song = Song.create("曲")
    variant = SongVariant.create("Alt", tmp_path / "a.wav", anchor_offset=anchor_offset)
    song.variants = [variant]
    song.selected_variant_id = variant.id
    session.set_song(song)
    return svc, engine, song, variant


def test_preview_repeated_enter_replaces_not_accumulates(tmp_path: Path) -> None:
    svc, engine, _song, variant = _svc_with_variant(tmp_path)
    svc.seek(8.0)
    gen0 = svc.preview_generation

    svc.begin_anchor_preview(0.5)
    assert svc.preview_generation == gen0 + 1
    assert svc.active_anchor_offset() == pytest.approx(0.5)
    assert engine._position == pytest.approx(7.5)

    # Re-enter with a new offset — replace, do not stack 0.5+0.25.
    svc.begin_anchor_preview(0.25)
    assert svc.preview_generation == gen0 + 1  # same session refresh
    assert svc.active_anchor_offset() == pytest.approx(0.25)
    assert variant.anchor_offset == pytest.approx(0.0)
    assert svc.position == pytest.approx(8.0)
    assert engine._position == pytest.approx(7.75)

    svc.end_anchor_preview()
    svc.begin_anchor_preview(1.0)
    assert svc.preview_generation == gen0 + 2  # new session
    assert svc.active_anchor_offset() == pytest.approx(1.0)


def test_preview_cancel_restores_entry_position_and_playing(tmp_path: Path) -> None:
    svc, engine, _song, variant = _svc_with_variant(tmp_path, anchor_offset=0.0)
    svc.seek(4.0)
    svc.play()
    assert engine.playing is True

    svc.begin_anchor_preview(1.0)
    assert engine._position == pytest.approx(3.0)
    # Operator seeks during preview (Song Time 6 → engine 5 under offset 1).
    svc.seek(6.0)
    assert svc.position == pytest.approx(6.0)

    svc.end_anchor_preview(restore_entry=True)
    assert svc.anchor_preview_active is False
    assert variant.anchor_offset == pytest.approx(0.0)
    assert svc.position == pytest.approx(4.0)
    assert engine._position == pytest.approx(4.0)
    assert engine.playing is True


def test_preview_while_stopped_paused_playing(tmp_path: Path) -> None:
    svc, engine, _song, variant = _svc_with_variant(tmp_path)

    # Stopped
    svc.seek(2.0)
    assert engine.playing is False
    svc.begin_anchor_preview(0.5)
    assert engine.playing is False
    assert svc.position == pytest.approx(2.0)
    svc.end_anchor_preview(restore_entry=True)
    assert engine.playing is False
    assert variant.anchor_offset == pytest.approx(0.0)

    # Playing
    svc.play()
    svc.begin_anchor_preview(0.2)
    assert engine.playing is True
    svc.end_anchor_preview(restore_entry=False)
    assert engine.playing is True

    # Paused
    svc.pause()
    svc.begin_anchor_preview(0.3)
    assert engine.playing is False
    svc.end_anchor_preview(restore_entry=True)
    assert engine.playing is False


def test_rapid_preview_cancel_apply_no_leak(tmp_path: Path) -> None:
    svc, engine, song, variant = _svc_with_variant(tmp_path)
    svc.seek(5.0)

    for _ in range(5):
        svc.begin_anchor_preview(0.4)
        svc.end_anchor_preview(restore_entry=True)
    assert svc.anchor_preview_active is False
    assert variant.anchor_offset == pytest.approx(0.0)
    assert svc.position == pytest.approx(5.0)

    svc.begin_anchor_preview(0.7)
    # Apply path: commit then end without entry restore.
    command = SetVariantAnchorOffsetCommand(
        variant_id=variant.id, old_offset=0.0, new_offset=0.7
    )
    command.redo(song)
    svc.end_anchor_preview(restore_entry=False)
    assert svc.anchor_preview_active is False
    assert variant.anchor_offset == pytest.approx(0.7)
    assert svc.active_anchor_offset() == pytest.approx(0.7)
    assert svc.position == pytest.approx(5.0)
    assert engine._position == pytest.approx(4.3)


def test_song_switch_ends_preview_via_set_current_song(tmp_path: Path) -> None:
    svc, _engine, song, variant = _svc_with_variant(tmp_path)
    other = Song.create("Other")
    svc.seek(3.0)
    svc.begin_anchor_preview(0.9)
    assert svc.anchor_preview_active is True
    svc.set_current_song(other)
    assert svc.anchor_preview_active is False
    assert variant.anchor_offset == pytest.approx(0.0)
    # Re-bind original song — mapping is committed only.
    svc.set_current_song(song)
    assert svc.active_anchor_offset() == pytest.approx(0.0)


def test_preview_apply_undo_redo_marks_fixed(tmp_path: Path) -> None:
    svc, _engine, song, variant = _svc_with_variant(tmp_path)
    mark = song.add_mark(1, 9.0, display_name="Cue")
    mark_time = mark.time_seconds
    svc.seek(9.0)
    svc.begin_anchor_preview(0.5)
    command = SetVariantAnchorOffsetCommand(
        variant_id=variant.id, old_offset=0.0, new_offset=0.5
    )
    command.redo(song)
    svc.end_anchor_preview(restore_entry=False)

    stack = UndoStack()
    stack.push(command)
    assert variant.anchor_offset == pytest.approx(0.5)
    assert mark.time_seconds == mark_time

    stack.undo(song)
    assert variant.anchor_offset == pytest.approx(0.0)
    assert mark.time_seconds == mark_time
    stack.redo(song)
    assert variant.anchor_offset == pytest.approx(0.5)
    assert mark.time_seconds == mark_time
    assert svc.anchor_preview_active is False
