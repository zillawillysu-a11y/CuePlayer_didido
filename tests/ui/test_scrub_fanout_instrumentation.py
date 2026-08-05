"""MainWindow scrub/play position paths must record fan-out spans."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from PySide6.QtWidgets import QApplication

from cueplayer.diagnostics import perf as perf_diag
from cueplayer.domain.models import Mark, Song
from cueplayer.ui.main_window import MainWindow


@pytest.fixture
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _song_with_marks(n: int = 20) -> Song:
    song = Song.create("測試")
    lane = song.mark_lanes[0]
    lane.cue_list_enabled = True
    marks = []
    for i in range(n):
        m = Mark.create(lane_index=lane.index, time_seconds=i * 0.1, display_name=f"m{i}")
        marks.append(m)
    song.marks = marks
    song.sort_marks()
    return song


def _stub_host(song: Song) -> SimpleNamespace:
    """Minimal host for fan-out helpers without constructing MainWindow."""
    host = SimpleNamespace()
    host.current_song = song
    host.engine = SimpleNamespace(duration=60.0)
    host.transport = MagicMock()
    host.monitor = MagicMock()
    host.timeline = MagicMock()
    host.timeline.pixels_per_second.return_value = 120.0
    host.video_sync = MagicMock()
    host.video_sync.engine_video_gated.return_value = True
    host.playback = MagicMock()
    host.playback.engine_to_song_time.side_effect = lambda s: float(s)
    host._refresh_output_timecode_clock = MagicMock()
    host._fanout_prev_seconds = None
    host._perf_tick_mono = None
    # Bind real methods
    host._perf_note_position_tick = MainWindow._perf_note_position_tick.__get__(host)
    host._perf_record_mark_density = MainWindow._perf_record_mark_density.__get__(host)
    host._on_scrub_preview = MainWindow._on_scrub_preview.__get__(host)
    host._sm_trace_worker_waiting = staticmethod(MainWindow._sm_trace_worker_waiting)
    return host


def test_scrub_preview_records_position_fanout(app: QApplication) -> None:
    perf_diag.set_enabled(True)
    perf_diag.clear()
    host = _stub_host(_song_with_marks(50))
    for t in (1.0, 1.1, 1.2, 2.0, 2.1):
        host._on_scrub_preview(t)
    snap = perf_diag.snapshot()
    assert snap["counters"].get("ui.position_fanout.calls", 0) >= 5
    assert snap["counters"].get("ui.scrub_fanout.calls", 0) >= 5
    assert "ui.position_fanout" in snap["spans"]
    assert "ui.scrub_fanout" in snap["spans"]
    assert "mark.lookup_ms" in snap["spans"]
    assert "monitor.position_sync_ms" in snap["spans"]
    assert snap["attrs"].get("perf.position_tick_source") == "scrub"
    text = perf_diag.report_text()
    assert "RESULT: OK" in text
    perf_diag.set_enabled(False)
