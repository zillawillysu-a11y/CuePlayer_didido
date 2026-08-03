"""UI / unit tests for Align Anchors draft + Apply commit."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from cueplayer.domain.anchor_mapping import (
    offset_from_anchors,
    song_to_variant_time,
)
from cueplayer.domain.models import Song
from cueplayer.domain.song_variant import SongVariant
from cueplayer.domain.undo import SetVariantAnchorOffsetCommand, UndoStack
from cueplayer.ui.align_anchors_dialog import AlignAnchorsDialog


@pytest.fixture(scope="module")
def qapp() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def test_offset_from_anchors_matches_mapping() -> None:
    song_a = 12.340
    var_a = 11.840
    draft = offset_from_anchors(song_a, var_a)
    assert draft == pytest.approx(0.5)
    assert song_to_variant_time(song_a, draft) == pytest.approx(var_a)


def test_align_anchors_dialog_shell_widgets(qapp: QApplication, tmp_path: Path) -> None:
    song = Song.create("開場")
    path = tmp_path / "床.wav"
    path.write_bytes(b"x")
    main = SongVariant.create("Main", path, anchor_offset=0.0)
    alt = SongVariant.create("Old mix", tmp_path / "old.wav", anchor_offset=0.25)
    song.variants = [main, alt]
    song.selected_variant_id = alt.id

    dialog = AlignAnchorsDialog(song)
    assert dialog.windowTitle() == "Align Anchors"
    assert dialog.variant_combo.count() == 2
    assert dialog.selected_variant() is alt
    assert "0.250" in dialog.applied_offset_label.text()
    assert dialog.draft_offset() == pytest.approx(0.25)
    assert dialog.draft_offset_spin.isEnabled() is True
    assert dialog.nudge_plus_1f.isEnabled() is True


def test_capture_anchors_computes_draft_without_mutating(
    qapp: QApplication, tmp_path: Path
) -> None:
    song = Song.create("曲")
    song.fps = 25.0
    variant = SongVariant.create("Main", tmp_path / "a.wav", anchor_offset=0.0)
    song.variants = [variant]
    song.selected_variant_id = variant.id

    dialog = AlignAnchorsDialog(
        song,
        get_song_playhead=lambda: 12.340,
        get_media_playhead=lambda: 11.840,
    )
    dialog.use_playhead_btn.click()
    dialog.use_media_playhead_btn.click()
    assert dialog.song_anchor_seconds() == pytest.approx(12.340)
    assert dialog.variant_anchor_seconds() == pytest.approx(11.840)
    assert dialog.draft_offset() == pytest.approx(0.5)
    assert variant.anchor_offset == pytest.approx(0.0)
    assert "0.500" in dialog.preview_area.text() or "+0.500" in dialog.preview_area.text()


def test_nudge_and_reset_draft_only(qapp: QApplication, tmp_path: Path) -> None:
    song = Song.create("曲")
    song.fps = 50.0
    variant = SongVariant.create("Main", tmp_path / "a.wav", anchor_offset=0.2)
    song.variants = [variant]
    song.selected_variant_id = variant.id
    dialog = AlignAnchorsDialog(song)
    assert dialog.draft_offset() == pytest.approx(0.2)
    dialog.nudge_plus_10ms.click()
    assert dialog.draft_offset() == pytest.approx(0.21)
    dialog.reset_btn.click()
    assert dialog.draft_offset() == pytest.approx(0.0)
    assert variant.anchor_offset == pytest.approx(0.2)


def test_apply_commits_offset_and_emits_command(
    qapp: QApplication, tmp_path: Path
) -> None:
    song = Song.create("曲")
    variant = SongVariant.create("Main", tmp_path / "a.wav", anchor_offset=0.5)
    song.variants = [variant]
    song.selected_variant_id = variant.id
    mark = song.add_mark(1, 4.0, display_name="Cue")
    mark_time = mark.time_seconds

    dialog = AlignAnchorsDialog(
        song,
        get_song_playhead=lambda: 10.0,
        get_media_playhead=lambda: 9.0,
    )
    committed: list[SetVariantAnchorOffsetCommand] = []
    dialog.offset_committed.connect(committed.append)

    dialog.use_playhead_btn.click()
    dialog.use_media_playhead_btn.click()
    assert dialog.draft_offset() == pytest.approx(1.0)
    dialog.apply_btn.click()

    assert variant.anchor_offset == pytest.approx(1.0)
    assert mark.time_seconds == mark_time
    assert len(committed) == 1
    assert committed[0].old_offset == pytest.approx(0.5)
    assert committed[0].new_offset == pytest.approx(1.0)
    assert "1.000" in dialog.applied_offset_label.text()
    assert dialog.is_draft_dirty() is False

    # Simulate MainWindow undo wiring.
    stack = UndoStack()
    stack.push(committed[0])
    stack.undo(song)
    assert variant.anchor_offset == pytest.approx(0.5)
    assert mark.time_seconds == mark_time
    stack.redo(song)
    assert variant.anchor_offset == pytest.approx(1.0)


def test_apply_noop_when_draft_matches_applied(
    qapp: QApplication, tmp_path: Path
) -> None:
    song = Song.create("曲")
    variant = SongVariant.create("Main", tmp_path / "a.wav", anchor_offset=0.5)
    song.variants = [variant]
    song.selected_variant_id = variant.id
    dialog = AlignAnchorsDialog(song)
    committed: list[object] = []
    dialog.offset_committed.connect(committed.append)
    dialog.apply_btn.click()
    assert variant.anchor_offset == pytest.approx(0.5)
    assert committed == []


def test_cancel_discards_draft(qapp: QApplication, tmp_path: Path, monkeypatch) -> None:
    song = Song.create("曲")
    variant = SongVariant.create("Main", tmp_path / "a.wav", anchor_offset=0.5)
    song.variants = [variant]
    song.selected_variant_id = variant.id
    dialog = AlignAnchorsDialog(song)
    dialog.nudge_plus_10ms.click()
    assert dialog.is_draft_dirty() is True
    monkeypatch.setattr(
        "cueplayer.ui.align_anchors_dialog.QMessageBox.question",
        lambda *a, **k: __import__("PySide6.QtWidgets", fromlist=["QMessageBox"]).QMessageBox.StandardButton.Yes,
    )
    dialog.reject()
    assert variant.anchor_offset == pytest.approx(0.5)


def test_preview_session_ephemeral_no_project_write(
    qapp: QApplication, tmp_path: Path, monkeypatch
) -> None:
    song = Song.create("曲")
    variant = SongVariant.create("Main", tmp_path / "a.wav", anchor_offset=0.0)
    song.variants = [variant]
    song.selected_variant_id = variant.id
    mark = song.add_mark(1, 2.0, display_name="Hit")
    mark_time = mark.time_seconds

    state = {"offset": None, "active": False}

    def begin(offset: float) -> None:
        state["offset"] = float(offset)
        state["active"] = True

    def end() -> None:
        state["offset"] = None
        state["active"] = False

    dialog = AlignAnchorsDialog(
        song,
        get_song_playhead=lambda: 10.0,
        get_media_playhead=lambda: 9.5,
        begin_preview=begin,
        end_preview=end,
        is_preview_active=lambda: bool(state["active"]),
    )
    dialog.use_playhead_btn.click()
    dialog.use_media_playhead_btn.click()
    assert dialog.draft_offset() == pytest.approx(0.5)
    dialog.preview_btn.click()
    assert state["active"] is True
    assert state["offset"] == pytest.approx(0.5)
    assert variant.anchor_offset == pytest.approx(0.0)
    assert mark.time_seconds == mark_time
    assert "PREVIEW" in dialog.preview_area.text()

    dialog.nudge_plus_10ms.click()
    assert state["offset"] == pytest.approx(0.51)
    assert variant.anchor_offset == pytest.approx(0.0)

    monkeypatch.setattr(
        "cueplayer.ui.align_anchors_dialog.QMessageBox.question",
        lambda *a, **k: __import__(
            "PySide6.QtWidgets", fromlist=["QMessageBox"]
        ).QMessageBox.StandardButton.Yes,
    )
    dialog.reject()
    assert state["active"] is False
    assert variant.anchor_offset == pytest.approx(0.0)

def test_preview_then_apply_commits_and_ends_preview(
    qapp: QApplication, tmp_path: Path
) -> None:
    song = Song.create("曲")
    variant = SongVariant.create("Main", tmp_path / "a.wav", anchor_offset=0.0)
    song.variants = [variant]
    song.selected_variant_id = variant.id
    state = {"active": False}

    dialog = AlignAnchorsDialog(
        song,
        begin_preview=lambda o: state.update(active=True, offset=float(o)),
        end_preview=lambda: state.update(active=False),
        is_preview_active=lambda: bool(state["active"]),
    )
    dialog.draft_offset_spin.setValue(0.75)
    dialog.preview_btn.click()
    assert state["active"] is True
    dialog.apply_btn.click()
    assert variant.anchor_offset == pytest.approx(0.75)
    assert state["active"] is False


def test_capture_song_mark(qapp: QApplication, tmp_path: Path, monkeypatch) -> None:
    song = Song.create("曲")
    variant = SongVariant.create("Main", tmp_path / "a.wav")
    song.variants = [variant]
    song.selected_variant_id = variant.id
    song.add_mark(1, 3.25, display_name="Kick")
    dialog = AlignAnchorsDialog(
        song,
        get_media_playhead=lambda: 3.0,
    )
    monkeypatch.setattr(
        "cueplayer.ui.align_anchors_dialog.QInputDialog.getItem",
        lambda *a, **k: ("00:03.250  ·  L1  ·  Kick", True),
    )
    dialog.use_mark_btn.click()
    dialog.use_media_playhead_btn.click()
    assert dialog.song_anchor_seconds() == pytest.approx(3.25)
    assert dialog.draft_offset() == pytest.approx(0.25)


def test_align_anchors_empty_variants(qapp: QApplication) -> None:
    song = Song.create("Empty")
    dialog = AlignAnchorsDialog(song)
    assert dialog.selected_variant() is None
    assert dialog.variant_combo.isEnabled() is False
