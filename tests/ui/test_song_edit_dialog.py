"""Song edit dialog helpers."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QComboBox, QDialog, QDialogButtonBox

from cueplayer.ui.song_edit_dialog import (
    SongDraft, SongEditDialog, _COL_LTC_SOURCE, suggest_ma_export_name,
)


EXPLICIT_MODES = ("off", "striped_file", "full_track_generator", "clip_generator")


def _accept_dialog(dialog: SongEditDialog) -> None:
    buttons = dialog.findChild(QDialogButtonBox)
    buttons.button(QDialogButtonBox.StandardButton.Ok).click()
    assert dialog.result() == QDialog.DialogCode.Accepted


@pytest.mark.parametrize("source,enabled,resolved", [
    ("auto", True, "striped_file"),
    ("source_left", True, "striped_file"),
    ("source_right", True, "striped_file"),
    ("generator", True, "full_track_generator"),
    ("generator", False, "off"),
])
def test_legacy_auto_displays_resolved_mode_but_accept_preserves_auto(source, enabled, resolved):
    project = SimpleNamespace(audio_output=SimpleNamespace(ltc_source=source, ltc_enabled=enabled))
    dialog = SongEditDialog([SongDraft(name="Legacy", ltc_source_mode="auto")], project=project)
    combo = dialog.table.cellWidget(0, _COL_LTC_SOURCE)
    assert isinstance(combo, QComboBox)
    assert combo.currentData() == resolved
    assert tuple(combo.itemData(i) for i in range(combo.count())) == EXPLICIT_MODES
    _accept_dialog(dialog)
    assert dialog.result_drafts()[0].ltc_source_mode == "auto"


@pytest.mark.parametrize("mode", EXPLICIT_MODES)
def test_legacy_auto_user_selects_explicit_mode_only_for_edited_row(mode):
    dialog = SongEditDialog([SongDraft(name="Edited"), SongDraft(name="Untouched")])
    combo = dialog.table.cellWidget(0, _COL_LTC_SOURCE)
    dialog.show()
    combo.showPopup()
    # Use real keyboard selection, including reselecting the resolved mode.
    QTest.keyClick(combo.view(), Qt.Key.Key_Home)
    for _ in range(combo.findData(mode)):
        QTest.keyClick(combo.view(), Qt.Key.Key_Down)
    QTest.keyClick(combo.view(), Qt.Key.Key_Return)
    assert combo.currentData() == mode
    _accept_dialog(dialog)
    assert [d.ltc_source_mode for d in dialog.result_drafts()] == [mode, "auto"]


@pytest.mark.parametrize("mode", EXPLICIT_MODES)
def test_explicit_ltc_mode_unchanged_on_accept(mode):
    dialog = SongEditDialog([SongDraft(name="Explicit", ltc_source_mode=mode)])
    _accept_dialog(dialog)
    assert dialog.result_drafts()[0].ltc_source_mode == mode


def test_programmatic_ltc_source_change_does_not_make_legacy_mode_explicit():
    dialog = SongEditDialog([SongDraft(name="Legacy")])
    combo = dialog.table.cellWidget(0, _COL_LTC_SOURCE)
    combo.setCurrentIndex(combo.findData("clip_generator"))
    _accept_dialog(dialog)
    assert dialog.result_drafts()[0].ltc_source_mode == "auto"


def test_suggest_ma_export_name_ascii_stem() -> None:
    assert suggest_ma_export_name("My_Song_v2") == "My_Song_v2"


def test_suggest_ma_export_name_chinese_only_uses_pinyin() -> None:
    assert suggest_ma_export_name("純影片") == "ChunYingPian"


def test_suggest_ma_export_name_mixed_uses_pinyin() -> None:
    result = suggest_ma_export_name("開場Intro")
    assert result == "KaiChangIntro"


def test_suggest_ma_export_name_blank_falls_back() -> None:
    assert suggest_ma_export_name("") == "Song"
    assert suggest_ma_export_name("   ") == "Song"
