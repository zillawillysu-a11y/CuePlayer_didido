"""Unit tests for optional performance diagnostics."""

from __future__ import annotations

from pathlib import Path

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


def test_flush_report_writes_log(tmp_path: Path) -> None:
    perf.set_enabled(True)
    perf.set_log_path(tmp_path / "cueplayer_perf.log")
    with perf.span("activate.song.total"):
        pass
    path = perf.flush_report(label="unit-test")
    assert path is not None
    assert path.is_file()
    body = path.read_text(encoding="utf-8")
    assert "unit-test" in body
    assert "activate.song.total" in body


def test_report_always_lists_video_pipeline_counters() -> None:
    perf.set_enabled(True)
    perf.clear()
    perf.note("video.pipeline_mode", "async_latest_wins")
    text = perf.report_text()
    assert "video.pipeline_mode: async_latest_wins" in text
    assert "video.async_schedule:" in text
    assert "video.async_coalesce:" in text
    assert "video.decode.async:" in text or "video.decode.async: (none" in text
    assert "video.convert:" in text or "video.convert: (none" in text
    assert "video.present:" in text or "video.present: (none" in text
