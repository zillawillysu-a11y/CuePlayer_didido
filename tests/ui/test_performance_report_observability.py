"""CUEPLAYER_PERF Tools action and B2 metric report coverage."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from cueplayer.diagnostics import perf as perf_diag
from cueplayer.domain.models import Project
from cueplayer.ui.main_window import MainWindow


@pytest.fixture
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_perf_enabled_tools_action_is_visible_and_calls_writer(
    app: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[MainWindow] = []

    def writer(window: MainWindow) -> None:
        calls.append(window)

    monkeypatch.setattr(MainWindow, "_write_performance_report", writer)
    perf_diag.set_enabled(True)
    try:
        window = MainWindow(Project.create("Perf action"))
        action = window._write_performance_report_action  # noqa: SLF001
        assert action is not None
        assert action.isVisible()
        assert "Performance Report" in action.text()
        action.trigger()
        assert calls == [window]
    finally:
        perf_diag.set_enabled(False)


def test_perf_report_includes_b2_observability_metrics() -> None:
    perf_diag.set_enabled(True)
    perf_diag.clear()
    try:
        perf_diag.record_ms("timeline.backdrop.incremental_strip_ms", 2.0)
        perf_diag.record_ms("timeline.backdrop.incremental_commit_ms", 3.0)
        perf_diag.record_ms("timeline.mark_layer.rebuild_ms", 4.0)
        perf_diag.record_ms("ui.event_loop_long_task_ms", 20.0)
        perf_diag.count("timeline.backdrop.incremental_callback_count", 5)
        perf_diag.count("timeline.backdrop.incremental_stale_discard", 2)
        perf_diag.note("timeline.backdrop.incremental_pending_work", 0)
        text = perf_diag.report_text()
    finally:
        perf_diag.set_enabled(False)

    for key in (
        "timeline.backdrop.incremental_strip_ms",
        "timeline.backdrop.incremental_commit_ms",
        "timeline.mark_layer.rebuild_ms",
        "ui.event_loop_long_task_ms",
        "timeline.backdrop.incremental_callback_count",
        "timeline.backdrop.incremental_stale_discard",
        "timeline.backdrop.incremental_pending_work",
    ):
        assert key in text
