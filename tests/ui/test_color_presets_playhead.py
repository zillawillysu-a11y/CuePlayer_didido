"""Persistent color presets and playhead color."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QSettings
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication, QColorDialog

from cueplayer.domain.models import Project
from cueplayer.persistence.project_store import project_from_dict, project_to_dict
from cueplayer.ui import color_presets as cp
from cueplayer.ui.timeline_widget import TimelineWidget


@pytest.fixture
def app(tmp_path, monkeypatch) -> QApplication:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    QSettings.setPath(
        QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp_path / "qs")
    )
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    return QApplication.instance() or QApplication([])


def test_user_presets_persist_across_reload(app: QApplication) -> None:
    cp.save_user_presets([])
    assert cp.add_user_preset("#aabbcc") is True
    assert "#aabbcc" in cp.load_user_presets()
    assert "#aabbcc" in cp.all_presets()
    # Simulate next launch reading the same QSettings store.
    assert cp.add_user_preset("#aabbcc") is False
    assert cp.load_user_presets() == ["#aabbcc"]


def test_color_dialog_custom_slots_round_trip(app: QApplication) -> None:
    QColorDialog.setCustomColor(0, QColor("#112233"))
    cp.persist_color_dialog_customs()
    QColorDialog.setCustomColor(0, QColor("#000000"))
    cp.restore_color_dialog_customs()
    restored = QColorDialog.customColor(0)
    if not isinstance(restored, QColor):
        restored = QColor.fromRgba(int(restored))
    assert restored.name().lower() == "#112233"


def test_playhead_color_persists_in_project() -> None:
    project = Project.create("Colors")
    project.playhead_color = "#00ffaa"
    restored = project_from_dict(project_to_dict(project))
    assert restored.playhead_color.lower() == "#00ffaa"


def test_timeline_applies_playhead_color(app: QApplication) -> None:
    widget = TimelineWidget()
    widget.apply_mark_line_settings(
        style="solid",
        width=1.0,
        dash_on=4.0,
        dash_off=4.0,
        playhead_color="#00aaff",
    )
    assert widget._playhead_color.lower() == "#00aaff"


def test_display_dialog_playhead_color_applies_live(app: QApplication) -> None:
    from cueplayer.ui.mark_display_dialog import MarkDisplayDialog

    project = Project.create("Colors")
    dialog = MarkDisplayDialog(project.songs[0], project=project)
    dialog.playhead_color._on_chosen("#336699")
    assert project.playhead_color.lower() == "#336699"
    dialog.close()
