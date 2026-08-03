"""UI tests for Align Anchors dialog shell (no offset application)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from cueplayer.domain.models import Song
from cueplayer.domain.song_variant import SongVariant
from cueplayer.ui.align_anchors_dialog import AlignAnchorsDialog


@pytest.fixture(scope="module")
def qapp() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


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
    assert dialog.song_anchor_label.text() == "—"
    assert dialog.variant_anchor_label.text() == "—"
    assert dialog.preview_area.objectName() == "alignPreviewArea"
    assert dialog.apply_btn is not None
    assert dialog.cancel_btn is not None
    assert dialog.preview_btn is not None
    assert dialog.reset_btn is not None
    assert dialog.draft_offset_spin.isEnabled() is False


def test_align_anchors_apply_stub_does_not_mutate_offset(
    qapp: QApplication, tmp_path: Path
) -> None:
    song = Song.create("曲")
    variant = SongVariant.create("Main", tmp_path / "a.wav", anchor_offset=0.5)
    song.variants = [variant]
    song.selected_variant_id = variant.id
    dialog = AlignAnchorsDialog(song)
    dialog.apply_btn.click()
    dialog.reset_btn.click()
    dialog.preview_btn.click()
    assert variant.anchor_offset == pytest.approx(0.5)
    assert "Shell only" in dialog.shell_status.text()


def test_align_anchors_empty_variants(qapp: QApplication) -> None:
    song = Song.create("Empty")
    dialog = AlignAnchorsDialog(song)
    assert dialog.selected_variant() is None
    assert dialog.variant_combo.isEnabled() is False
