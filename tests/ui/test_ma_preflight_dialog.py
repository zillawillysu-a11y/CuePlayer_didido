"""UI tests for MA Preflight dialog (Sprint 6 Task 4)."""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from cueplayer.domain.models import Project, Song
from cueplayer.domain.validation import (
    PreflightReport,
    ValidationReport,
    build_preflight_report,
    build_preflight_report_for_project,
    make_issue,
)
from cueplayer.ui.ma_preflight_dialog import (
    MaPreflightDialog,
    format_issue_target,
    navigation_target,
)


@pytest.fixture(scope="module")
def qapp() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def _sample_report() -> PreflightReport:
    raw = ValidationReport(context_label="Demo Show", rule_set_id="ma-preflight")
    raw.extend(
        [
            make_issue(
                "MA001",
                "error",
                "Song MA Export Name has non-ASCII",
                subject="song:s1",
                path="song.ma_export_name",
                details={"song_name": "開場", "value": "主歌"},
            ),
            make_issue(
                "MA050",
                "warning",
                "Sequence 'Opening' has no cues",
                subject="sequence:s1:main",
                details={"song_id": "s1", "song_name": "開場", "label": "Opening"},
            ),
            make_issue(
                "MA052",
                "warning",
                "Cue is not on an export lane",
                subject="mark:m9",
                details={"song_id": "s1", "song_name": "開場"},
            ),
            make_issue(
                "MA150",
                "information",
                "Total songs: 1 (1 included)",
                subject="project:songs",
                details={"total": 1},
            ),
        ]
    )
    return build_preflight_report(raw, title="Demo Show")


def test_dialog_layout_and_summary(qapp: QApplication) -> None:
    report = _sample_report()
    dialog = MaPreflightDialog(report)
    assert dialog.windowTitle() == "MA Preflight"
    assert dialog.error_count_label.text() == "Errors: 1"
    assert dialog.warning_count_label.text() == "Warnings: 2"
    assert dialog.info_count_label.text() == "Information: 1"
    assert dialog.table.columnCount() == 4
    assert dialog.table.rowCount() == 4
    assert dialog.table.horizontalHeaderItem(0).text() == "Code"
    assert dialog.table.horizontalHeaderItem(1).text() == "Severity"
    assert dialog.table.horizontalHeaderItem(2).text() == "Song / Object"
    assert dialog.table.horizontalHeaderItem(3).text() == "Message"
    # Sorted: error first
    assert dialog.table.item(0, 0).text() == "MA001"
    assert dialog.table.item(0, 1).text() == "error"
    assert "開場" in dialog.table.item(0, 2).text()
    dialog.close()


def test_navigation_helpers() -> None:
    report = _sample_report()
    by_code = {r.code.value: r for r in report.issues}
    assert navigation_target(by_code["MA001"]) == ("s1", "song", "s1")
    assert navigation_target(by_code["MA052"]) == ("s1", "mark", "m9")
    assert navigation_target(by_code["MA050"]) == ("s1", "sequence", "s1:main")
    assert navigation_target(by_code["MA150"]) is None
    assert "開場" in format_issue_target(by_code["MA001"])


def test_double_click_emits_navigate(qapp: QApplication) -> None:
    report = _sample_report()
    dialog = MaPreflightDialog(report)
    seen: list[tuple[str, str, str]] = []
    dialog.navigate_requested.connect(
        lambda sid, kind, oid: seen.append((sid, kind, oid))
    )
    # Row 0 = MA001 song
    dialog.table.doubleClicked.emit(dialog.table.model().index(0, 0))
    assert seen == [("s1", "song", "s1")]
    # Find mark row
    mark_row = next(
        i
        for i in range(dialog.table.rowCount())
        if dialog.table.item(i, 0).text() == "MA052"
    )
    dialog.table.doubleClicked.emit(dialog.table.model().index(mark_row, 0))
    assert seen[-1] == ("s1", "mark", "m9")
    # Info row — no navigate
    info_row = next(
        i
        for i in range(dialog.table.rowCount())
        if dialog.table.item(i, 0).text() == "MA150"
    )
    before = len(seen)
    dialog.table.doubleClicked.emit(dialog.table.model().index(info_row, 0))
    assert len(seen) == before
    dialog.close()


def test_dialog_requires_preflight_report(qapp: QApplication) -> None:
    with pytest.raises(TypeError, match="PreflightReport"):
        MaPreflightDialog("not a report")  # type: ignore[arg-type]


def test_dialog_read_only_project_unchanged(qapp: QApplication) -> None:
    project = Project.create("Show")
    song = Song.create("曲目")
    song.ma_export_name = ""
    project.songs.append(song)
    before_name = project.name
    before_export = song.ma_export_name
    report = build_preflight_report_for_project(project)
    dialog = MaPreflightDialog(report)
    assert dialog.table.rowCount() >= 1
    dialog.close()
    assert project.name == before_name
    assert song.ma_export_name == before_export


def test_dialog_export_gate_blocks_continue_on_errors(qapp: QApplication) -> None:
    from PySide6.QtWidgets import QLabel

    report = _sample_report()
    assert report.has_errors is True
    dialog = MaPreflightDialog(report, mode="export_gate", can_continue=False)
    assert dialog.windowTitle() == "MA Preflight — Export"
    assert dialog.continue_btn is None
    hint = dialog.findChild(QLabel, "preflightHint")
    assert hint is not None
    assert "blocked" in hint.text().lower()
    dialog.close()


def test_dialog_export_gate_continue_when_allowed(qapp: QApplication) -> None:
    from cueplayer.domain.validation import ValidationReport, build_preflight_report, make_issue

    raw = ValidationReport(context_label="Demo", rule_set_id="ma-preflight")
    raw.extend(
        [
            make_issue(
                "MA050",
                "warning",
                "empty seq",
                subject="sequence:s1:main",
                details={"song_id": "s1"},
            ),
            make_issue(
                "MA150",
                "information",
                "Total songs: 1",
                subject="project:songs",
            ),
        ]
    )
    report = build_preflight_report(raw, title="Demo")
    dialog = MaPreflightDialog(report, mode="export_gate", can_continue=True)
    assert dialog.continue_btn is not None
    assert dialog.continue_btn.text() == "Continue Export"
    dialog.close()


def test_present_export_preflight_gate_policy(
    qapp: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    from cueplayer.application.ma_preflight_export_gate import (
        evaluate_ma_preflight_for_export,
    )
    from cueplayer.ui.ma_preflight_dialog import (
        MaPreflightDialog,
        present_export_preflight_gate,
    )

    project = Project.create("Show")
    project.songs.clear()
    song = Song.create("開場")
    song.ma_export_name = ""
    project.songs.append(song)
    gate = evaluate_ma_preflight_for_export(project)
    assert gate.allow_export is False

    monkeypatch.setattr(
        MaPreflightDialog,
        "exec",
        lambda self: int(MaPreflightDialog.DialogCode.Accepted),
    )
    # Even if dialog somehow Accepted, errors still block.
    assert present_export_preflight_gate(gate) is False


def test_dialog_module_has_no_exporter_imports() -> None:
    import inspect

    import cueplayer.ui.ma_preflight_dialog as mod

    src = inspect.getsource(mod)
    assert "cueplayer.exporters" not in src
    assert "run_ma_preflight" not in src
    assert "ma_preflight_rules" not in src
    assert "build_preflight_report_for_project" not in src
    assert "build_ma_preflight_context" not in src
