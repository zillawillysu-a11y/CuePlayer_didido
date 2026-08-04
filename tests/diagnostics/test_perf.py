"""Unit tests for optional performance diagnostics."""

from __future__ import annotations

from cueplayer.diagnostics import perf


def setup_function() -> None:
    perf.set_enabled(False)
    perf.clear()


def teardown_function() -> None:
    perf.set_enabled(False)
    perf.clear()


def test_perf_disabled_is_noop() -> None:
    perf.set_enabled(False)
    with perf.span("activate.song.total"):
        pass
    perf.count("ui.position_fanout.calls")
    snap = perf.snapshot()
    assert snap["spans"] == {}
    assert snap["counters"] == {}


def test_perf_records_when_enabled() -> None:
    perf.set_enabled(True)
    with perf.span("activate.song.total"):
        pass
    with perf.span("activate.waveform_arm"):
        pass
    perf.count("timeline.paint.calls", 3)
    perf.note("activate.waveform_path", "ram_hit")
    snap = perf.snapshot()
    assert "activate.song.total" in snap["spans"]
    assert snap["spans"]["activate.song.total"]["count"] == 1
    assert snap["counters"]["timeline.paint.calls"] == 3
    assert snap["attrs"]["activate.waveform_path"] == "ram_hit"
    assert "activate.song.total" in snap["last_activate_ms"]
    text = perf.report_text()
    assert "activate.song.total" in text
