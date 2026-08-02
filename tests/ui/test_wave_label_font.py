"""Display Settings: shared Wave Cue / Wave Note label font size."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from cueplayer.domain.models import Project
from cueplayer.persistence.project_store import project_from_dict, project_to_dict
from cueplayer.ui.mark_display_dialog import MarkDisplayDialog
from cueplayer.ui.timeline_widget import TimelineWidget


@pytest.fixture
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_wave_label_font_defaults_and_roundtrip() -> None:
    project = Project.create("Font")
    assert project.wave_label_font_px == 10
    project.wave_label_font_px = 16
    restored = project_from_dict(project_to_dict(project))
    assert restored.wave_label_font_px == 16


def test_display_dialog_sets_wave_label_font(app: QApplication) -> None:
    project = Project.create("FontDlg")
    dialog = MarkDisplayDialog(project.songs[0], project=project)
    dialog.wave_label_font.setValue(18)
    assert project.wave_label_font_px == 18
    dialog.close()


def test_timeline_applies_wave_label_font(app: QApplication) -> None:
    widget = TimelineWidget()
    widget.apply_mark_line_settings(
        style="solid",
        width=1.0,
        dash_on=4.0,
        dash_off=4.0,
        wave_label_font_px=14,
    )
    assert widget._wave_label_font_px == 14
