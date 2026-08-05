"""Prove Dense Mark / position-fanout hooks actually record (play + scrub)."""

from __future__ import annotations

from cueplayer.diagnostics import perf as perf_diag


def setup_function() -> None:
    perf_diag.set_enabled(False)
    perf_diag.clear()


def teardown_function() -> None:
    perf_diag.set_enabled(False)
    perf_diag.clear()


def test_report_live_check_invalid_when_no_ticks() -> None:
    perf_diag.set_enabled(True)
    perf_diag.clear()
    perf_diag.note("video.pipeline_mode", "async_latest_wins")
    text = perf_diag.report_text()
    assert "INSTRUMENTATION LIVE CHECK:" in text
    assert "RESULT: INVALID" in text
    assert "ui.position_fanout.calls: 0" in text


def test_report_live_check_ok_after_fanout_calls() -> None:
    perf_diag.set_enabled(True)
    perf_diag.clear()
    with perf_diag.span("ui.position_fanout"):
        with perf_diag.span("mark.lookup_ms"):
            pass
        with perf_diag.span("monitor.position_sync_ms"):
            pass
    perf_diag.count("ui.position_fanout.calls")
    perf_diag.note("perf.position_tick_source", "engine")
    perf_diag.note("perf.position_tick_song_time", 12.5)
    text = perf_diag.report_text()
    assert "RESULT: OK" in text
    assert "span ui.position_fanout:" in text
    assert "(none)" not in [
        line for line in text.splitlines() if "span ui.position_fanout:" in line
    ][0]


def test_scrub_fanout_appears_in_report() -> None:
    perf_diag.set_enabled(True)
    perf_diag.clear()
    with perf_diag.span("ui.position_fanout"):
        with perf_diag.span("ui.scrub_fanout"):
            pass
    perf_diag.count("ui.position_fanout.calls")
    perf_diag.count("ui.scrub_fanout.calls", 3)
    text = perf_diag.report_text()
    assert "ui.scrub_fanout.calls: 3" in text
    assert "RESULT: OK" in text


def test_seek_gop_notes_in_dense_mark_section() -> None:
    perf_diag.set_enabled(True)
    perf_diag.clear()
    perf_diag.count("ui.position_fanout.calls")
    perf_diag.note("video.seek.frames_to_target", 88)
    perf_diag.note("video.seek.keyframe_pts", 10.0)
    perf_diag.note("video.seek.keyframe_distance_s", 2.933)
    perf_diag.note("video.seek.gop_frames_estimate", 88)
    text = perf_diag.report_text()
    assert "note video.seek.frames_to_target: 88" in text
    assert "note video.seek.keyframe_distance_s: 2.933" in text
