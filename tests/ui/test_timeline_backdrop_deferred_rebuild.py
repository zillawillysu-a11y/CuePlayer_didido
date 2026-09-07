"""Regression coverage for deferred Timeline static-backdrop rebuilds."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication

from cueplayer.domain.models import Song
from cueplayer.ui.timeline_widget import TimelineWidget


@pytest.fixture
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _timeline(app: QApplication) -> TimelineWidget:
    widget = TimelineWidget()
    widget.resize(800, 320)
    song = Song.create("Deferred backdrop")
    song.duration_seconds = 120.0
    widget.set_song(song)
    app.processEvents()
    app.processEvents()
    return widget


def test_rapid_invalidations_coalesce_to_one_latest_rebuild(
    app: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    widget = _timeline(app)
    calls: list[str] = []
    original = widget._rebuild_scrub_backdrop  # noqa: SLF001

    def tracked(reason: str = "rebuild") -> None:
        calls.append(reason)
        original(reason)

    monkeypatch.setattr(widget, "_rebuild_scrub_backdrop", tracked)
    widget._invalidate_scrub_backdrop(reason="first")  # noqa: SLF001
    widget._invalidate_scrub_backdrop(reason="middle")  # noqa: SLF001
    widget._invalidate_scrub_backdrop(reason="last")  # noqa: SLF001

    assert widget._scrub_backdrop_rebuild_pending  # noqa: SLF001
    assert widget._scrub_backdrop_rebuild_reason == "last"  # noqa: SLF001
    app.processEvents()

    assert calls == ["last"]
    assert not widget._scrub_backdrop_rebuild_pending  # noqa: SLF001


def test_deferred_zoom_rebuild_uses_latest_zoom_state(app: QApplication) -> None:
    widget = _timeline(app)
    widget._pixels_per_second = 64.0  # noqa: SLF001
    widget._invalidate_scrub_backdrop(reason="zoom_first")  # noqa: SLF001
    widget._pixels_per_second = 137.0  # noqa: SLF001
    widget._invalidate_scrub_backdrop(reason="zoom_last")  # noqa: SLF001

    app.processEvents()

    assert widget._scrub_backdrop_pps == pytest.approx(137.0)  # noqa: SLF001
    assert widget._scrub_backdrop_geometry_ok()  # noqa: SLF001


def test_mark_drop_finishes_with_rebuilt_backdrop(app: QApplication) -> None:
    widget = _timeline(app)
    assert widget._song is not None  # noqa: SLF001
    widget._song.add_mark(0, 3.0)  # noqa: SLF001
    widget.bump_mark_backdrop_revision(reason="mark_drop")

    app.processEvents()

    assert widget._mark_backdrop_baked_revision == widget._mark_backdrop_revision  # noqa: SLF001
    assert not widget._scrub_backdrop_rebuild_pending  # noqa: SLF001


def test_mark_revision_does_not_rasterize_static_waveform(
    app: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    widget = _timeline(app)
    widget._rebuild_scrub_backdrop(reason="seed")  # noqa: SLF001
    calls: list[int] = []
    original = widget._paint_static_layers  # noqa: SLF001

    def tracked(*args, **kwargs):  # noqa: ANN002,ANN003
        calls.append(1)
        return original(*args, **kwargs)

    monkeypatch.setattr(widget, "_paint_static_layers", tracked)
    assert widget._song is not None  # noqa: SLF001
    widget._song.add_mark(0, 4.0)
    widget.bump_mark_backdrop_revision(reason="mark_create")

    assert calls == []
    assert widget._mark_backdrop_baked_revision == widget._mark_backdrop_revision  # noqa: SLF001


def test_incremental_zoom_latest_generation_wins(app: QApplication) -> None:
    widget = _timeline(app)
    widget._rebuild_scrub_backdrop(reason="seed")  # noqa: SLF001
    widget._pixels_per_second = 96.0  # noqa: SLF001
    widget._start_incremental_scrub_backdrop_build("zoom_idle")  # noqa: SLF001
    old_generation = widget._scrub_backdrop_build_generation  # noqa: SLF001
    widget._pixels_per_second = 143.0  # noqa: SLF001
    widget._invalidate_scrub_backdrop(reason="zoom_idle", retain_for_deferred_rebuild=True)  # noqa: SLF001
    for _ in range(48):
        app.processEvents()
        if widget._scrub_backdrop_build_state is None:  # noqa: SLF001
            break

    assert widget._scrub_backdrop_build_generation > old_generation  # noqa: SLF001
    assert widget._scrub_backdrop_pps == pytest.approx(143.0)  # noqa: SLF001
    assert widget._scrub_backdrop_build_state is None  # noqa: SLF001


def test_pending_callback_is_safe_when_widget_is_destroyed(
    app: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    widget = _timeline(app)
    calls: list[str] = []
    original = widget._rebuild_scrub_backdrop  # noqa: SLF001

    def tracked(reason: str = "rebuild") -> None:
        calls.append(reason)
        original(reason)

    monkeypatch.setattr(widget, "_rebuild_scrub_backdrop", tracked)
    widget._invalidate_scrub_backdrop(reason="destroy")  # noqa: SLF001
    widget.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()

    assert calls == []


def test_incremental_pending_strip_is_safe_when_widget_is_destroyed(
    app: QApplication,
) -> None:
    widget = _timeline(app)
    widget._rebuild_scrub_backdrop(reason="seed")  # noqa: SLF001
    widget._start_incremental_scrub_backdrop_build("zoom_idle")  # noqa: SLF001
    assert widget._scrub_backdrop_build_state is not None  # noqa: SLF001
    widget.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()
