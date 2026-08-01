"""Output quick toggles wrap instead of clipping when the panel is narrow."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from cueplayer.ui.output_quick_toggles import OutputQuickToggles, _WRAP_WIDTH_PX


@pytest.fixture
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_toggles_stay_single_row_when_wide(app: QApplication) -> None:
    toggles = OutputQuickToggles()
    toggles.show()
    toggles.resize(320, 40)
    app.processEvents()
    toggles._fit_to_width()  # noqa: SLF001
    assert not toggles._wrapped  # noqa: SLF001
    assert toggles._translate.text() == "TRANS"


def test_toggles_wrap_to_two_rows_when_narrow(app: QApplication) -> None:
    toggles = OutputQuickToggles()
    toggles.show()
    toggles.resize(max(80, _WRAP_WIDTH_PX - 40), 80)
    app.processEvents()
    toggles._fit_to_width()  # noqa: SLF001
    assert toggles._wrapped  # noqa: SLF001
    assert toggles._compact_style  # noqa: SLF001
    # Labels stay complete — wrapping avoids "TRANS" → "RAN" clipping.
    assert toggles._translate.text() == "TRANS"
    assert toggles._note.text() == "Note"
    assert toggles._mtc.text() == "MTC"
    assert toggles._ltc.text() == "LTC"
    # Each chip should be at least as wide as its text after wrap.
    for chip in toggles._all_chips():  # noqa: SLF001
        assert chip.width() >= chip.fontMetrics().horizontalAdvance(chip.text())
