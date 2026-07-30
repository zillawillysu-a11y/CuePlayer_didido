"""Mark Manager NOW display assignment."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication, QComboBox, QDialog

from cueplayer.domain.models import Song
from cueplayer.persistence.mark_template import build_template, save_mark_template
from cueplayer.ui.mark_manager_dialog import MarkManagerDialog, _COL_NOW


@pytest.fixture
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _set_now_role(dialog: MarkManagerDialog, row: int, role: int) -> None:
    combo = dialog.table.cellWidget(row, _COL_NOW)
    assert isinstance(combo, QComboBox)
    idx = combo.findData(role)
    combo.setCurrentIndex(idx if idx >= 0 else 0)


def test_mark_manager_accept_saves_now_display_assignment(app: QApplication) -> None:
    song = Song.create("NOW")
    dialog = MarkManagerDialog(song)
    for row in range(dialog.table.rowCount()):
        _set_now_role(dialog, row, 0)
    _set_now_role(dialog, 0, 1)
    _set_now_role(dialog, 1, 2)
    _set_now_role(dialog, 2, 0)

    draft = dialog._collect_draft_lanes()
    assert draft is not None
    dialog._song.mark_lanes = draft
    dialog._apply_now_lanes_to_song()

    assert song.now_lanes_configured is True
    assert 1 in song.now_primary_lanes
    assert 2 in song.now_secondary_lanes
    assert 3 not in song.now_primary_lanes
    assert 3 not in song.now_secondary_lanes


def test_mark_manager_save_settings_includes_now_display(
    app: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    song = Song.create("NOW")
    dialog = MarkManagerDialog(song)
    for row in range(dialog.table.rowCount()):
        _set_now_role(dialog, row, 0)
    _set_now_role(dialog, 0, 1)
    _set_now_role(dialog, 1, 2)

    path = tmp_path / "marks.cueplayer-marks.json"

    def _fake_save(_parent, _title, _suggested, _filter) -> tuple[str, str]:
        return str(path), ""

    monkeypatch.setattr(
        "cueplayer.ui.mark_manager_dialog.QFileDialog.getSaveFileName",
        _fake_save,
    )
    monkeypatch.setattr(
        "cueplayer.ui.mark_manager_dialog.QMessageBox.information",
        lambda *args, **kwargs: None,
    )
    dialog._save_template()

    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["now_primary_lanes"] == [1]
    assert data["now_secondary_lanes"] == [2]
