"""Align Anchors beta — UI chrome / rapid-action / Apply guard regression tests."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication, QMessageBox

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


class _PreviewStub:
    def __init__(self) -> None:
        self.active = False
        self.offset: float | None = None
        self.begin_count = 0
        self.end_calls: list[dict] = []

    def begin(self, offset: float) -> None:
        self.begin_count += 1
        self.offset = float(offset)
        self.active = True

    def end(self, *, restore_entry: bool = False) -> None:
        self.end_calls.append({"restore_entry": restore_entry})
        self.active = False
        self.offset = None


def test_preview_banner_and_variant_lock(qapp: QApplication, tmp_path: Path) -> None:
    song = Song.create("曲")
    main = SongVariant.create("Main", tmp_path / "a.wav", anchor_offset=0.0)
    alt = SongVariant.create("Alt", tmp_path / "b.wav", anchor_offset=0.1)
    song.variants = [main, alt]
    song.selected_variant_id = main.id
    stub = _PreviewStub()
    dialog = AlignAnchorsDialog(
        song,
        begin_preview=stub.begin,
        end_preview=stub.end,
        is_preview_active=lambda: stub.active,
    )
    assert dialog.preview_banner.isHidden() is True
    assert dialog.variant_combo.isEnabled() is True
    assert dialog.apply_btn.isEnabled() is False

    dialog.draft_offset_spin.setValue(0.4)
    assert dialog.apply_btn.isEnabled() is True
    dialog.preview_btn.click()
    assert stub.active is True
    assert dialog.preview_banner.isHidden() is False
    assert "PREVIEW MODE" in dialog.preview_banner.text()
    assert dialog.variant_combo.isEnabled() is False
    assert dialog.preview_btn.text() == "Update Preview"

    dialog.preview_btn.click()  # refresh — still one session
    assert stub.begin_count == 2
    assert stub.offset == pytest.approx(0.4)


def test_rapid_preview_cancel_restore_entry(
    qapp: QApplication, tmp_path: Path, monkeypatch
) -> None:
    song = Song.create("曲")
    variant = SongVariant.create("Main", tmp_path / "a.wav", anchor_offset=0.0)
    song.variants = [variant]
    song.selected_variant_id = variant.id
    stub = _PreviewStub()
    dialog = AlignAnchorsDialog(
        song,
        begin_preview=stub.begin,
        end_preview=stub.end,
        is_preview_active=lambda: stub.active,
    )
    for i in range(3):
        dialog.draft_offset_spin.setValue(0.1 * (i + 1))
        dialog.preview_btn.click()
        assert stub.active is True
    monkeypatch.setattr(
        AlignAnchorsDialog,
        "_confirm_discard_draft",
        lambda self: True,
    )
    dialog.reject()
    assert stub.active is False
    assert stub.end_calls[-1]["restore_entry"] is True
    assert variant.anchor_offset == pytest.approx(0.0)


def test_apply_emits_one_command_and_exits_preview(
    qapp: QApplication, tmp_path: Path
) -> None:
    song = Song.create("曲")
    variant = SongVariant.create("Main", tmp_path / "a.wav", anchor_offset=0.0)
    song.variants = [variant]
    song.selected_variant_id = variant.id
    stub = _PreviewStub()
    dialog = AlignAnchorsDialog(
        song,
        begin_preview=stub.begin,
        end_preview=stub.end,
        is_preview_active=lambda: stub.active,
    )
    committed: list[SetVariantAnchorOffsetCommand] = []
    dialog.offset_committed.connect(committed.append)

    dialog.draft_offset_spin.setValue(0.55)
    dialog.preview_btn.click()
    dialog.apply_btn.click()
    # Double-click Apply must not emit twice.
    dialog.apply_btn.click()

    assert len(committed) == 1
    assert committed[0].new_offset == pytest.approx(0.55)
    assert variant.anchor_offset == pytest.approx(0.55)
    assert stub.active is False
    assert stub.end_calls[-1]["restore_entry"] is False
    assert dialog.apply_btn.isEnabled() is False  # clean after apply

    stack = UndoStack()
    stack.push(committed[0])
    stack.undo(song)
    assert variant.anchor_offset == pytest.approx(0.0)
    stack.redo(song)
    assert variant.anchor_offset == pytest.approx(0.55)


def test_variant_switch_blocked_while_previewing(
    qapp: QApplication, tmp_path: Path
) -> None:
    song = Song.create("曲")
    main = SongVariant.create("Main", tmp_path / "a.wav", anchor_offset=0.0)
    alt = SongVariant.create("Alt", tmp_path / "b.wav", anchor_offset=0.2)
    song.variants = [main, alt]
    song.selected_variant_id = main.id
    stub = _PreviewStub()
    dialog = AlignAnchorsDialog(
        song,
        begin_preview=stub.begin,
        end_preview=stub.end,
        is_preview_active=lambda: stub.active,
    )
    dialog.draft_offset_spin.setValue(0.3)
    dialog.preview_btn.click()
    assert dialog.variant_combo.isEnabled() is False
    # Ending preview unlocks combo.
    dialog._end_preview_session(restore_entry=True)
    assert stub.active is False
    assert dialog.variant_combo.isEnabled() is True
