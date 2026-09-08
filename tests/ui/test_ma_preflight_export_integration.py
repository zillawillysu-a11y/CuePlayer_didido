"""Integration tests: MA Preflight gate before Show Patch export."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QMessageBox

from cueplayer.domain.models import Mark, Project, Song
from cueplayer.ui.show_patch_page import ShowPatchPage


@pytest.fixture(scope="module")
def qapp() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def _project_with_valid_song() -> Project:
    project = Project.create("Show")
    project.songs.clear()
    song = Song.create("Opening")
    song.ma_export_name = "Opening"
    song.marks = [Mark.create(1, 1.0, "Cue1")]
    project.songs.append(song)
    project.ma_export.export_mode = "timecode_only"  # skip install-name prompt
    return project


def _project_with_error() -> Project:
    project = Project.create("Show")
    project.songs.clear()
    song = Song.create("OpeningBad")
    song.ma_export_name = ""  # MA002
    song.marks = [Mark.create(1, 1.0, "Cue1")]
    project.songs.append(song)
    project.ma_export.export_mode = "timecode_only"
    return project


def _prepare_page(project: Project, out: Path) -> ShowPatchPage:
    page = ShowPatchPage()
    page.set_project(project)
    page.out_dir.setText(str(out))
    # Ensure at least one song is checked for export slots.
    for row in range(page.song_pick.count()):
        item = page.song_pick.item(row)
        if item is not None:
            item.setCheckState(Qt.CheckState.Checked)
    page.refresh()
    assert page._slots, "expected export slots after checking songs"
    return page


def _patch_message_boxes(monkeypatch: pytest.MonkeyPatch) -> None:
    """Avoid modal QMessageBox hangs under offscreen Qt."""
    for name in ("information", "warning", "question", "critical"):
        monkeypatch.setattr(
            f"cueplayer.ui.show_patch_page.QMessageBox.{name}",
            lambda *a, **k: QMessageBox.StandardButton.Yes,
        )


def test_export_aborts_when_preflight_gate_denies(
    qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []
    _patch_message_boxes(monkeypatch)

    def deny_present(*_a, **_k) -> bool:
        calls.append("gate")
        return False

    monkeypatch.setattr(
        "cueplayer.ui.ma_preflight_dialog.present_export_preflight_gate",
        deny_present,
    )
    monkeypatch.setattr(
        "cueplayer.application.ma_preflight_export_gate.evaluate_ma_preflight_for_export",
        lambda project: MagicMock(allow_export=False),
    )

    def boom(*_a, **_k):
        calls.append("export")
        raise AssertionError("exporters must not run when gate denies")

    monkeypatch.setattr(
        "cueplayer.ui.show_patch_page.Ma2Exporter.export_show_to_directory",
        boom,
    )
    monkeypatch.setattr(
        "cueplayer.ui.show_patch_page.Ma3Exporter.export_show_to_directory",
        boom,
    )

    page = _prepare_page(_project_with_error(), tmp_path)
    page._export()
    assert calls == ["gate"]


def test_export_runs_after_preflight_allows(
    qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []
    _patch_message_boxes(monkeypatch)

    monkeypatch.setattr(
        "cueplayer.ui.ma_preflight_dialog.present_export_preflight_gate",
        lambda *_a, **_k: True,
    )
    monkeypatch.setattr(
        "cueplayer.application.ma_preflight_export_gate.evaluate_ma_preflight_for_export",
        lambda project: MagicMock(allow_export=True),
    )

    def fake_export(self, plans, directory, **_kwargs):  # noqa: ANN001
        calls.append("export")
        return {"song:0": Path(directory) / "Opening.xml"}

    monkeypatch.setattr(
        "cueplayer.ui.show_patch_page.Ma2Exporter.export_show_to_directory",
        fake_export,
    )
    monkeypatch.setattr(
        "cueplayer.ui.show_patch_page.Ma3Exporter.export_show_to_directory",
        fake_export,
    )

    page = _prepare_page(_project_with_valid_song(), tmp_path)
    finished = MagicMock()
    page.export_finished.connect(finished)
    page._export()
    assert calls == ["export"]
    finished.assert_called_once()


def test_real_gate_blocks_error_project(
    qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """End-to-end: real evaluate + dialog reject path blocks exporter."""
    from cueplayer.application.ma_preflight_export_gate import (
        evaluate_ma_preflight_for_export,
    )
    from cueplayer.ui import ma_preflight_dialog as dlg_mod

    _patch_message_boxes(monkeypatch)

    project = _project_with_error()
    gate = evaluate_ma_preflight_for_export(project)
    assert gate.allow_export is False

    def auto_reject(self) -> int:  # noqa: ANN001
        return int(dlg_mod.QDialog.DialogCode.Rejected)

    monkeypatch.setattr(dlg_mod.MaPreflightDialog, "exec", auto_reject)

    export_calls: list[str] = []

    def boom(*_a, **_k):
        export_calls.append("export")
        raise AssertionError("must not export")

    monkeypatch.setattr(
        "cueplayer.ui.show_patch_page.Ma2Exporter.export_show_to_directory",
        boom,
    )
    monkeypatch.setattr(
        "cueplayer.ui.show_patch_page.Ma3Exporter.export_show_to_directory",
        boom,
    )

    page = _prepare_page(project, tmp_path)
    page._export()
    assert export_calls == []
