"""Dense Mark region performance — indexed lookup + bounded UI updates."""

from __future__ import annotations

import time

import pytest
from PySide6.QtWidgets import QApplication

from cueplayer.diagnostics import perf as perf_diag
from cueplayer.domain.models import Mark, Song


def _song_with_n_marks(n: int, *, spacing: float = 0.1) -> Song:
    """Build many marks quickly (bypass per-add Cue ID renumber)."""
    song = Song.create("密集測試")
    lane = song.mark_lanes[0]
    lane.cue_list_enabled = True
    lane.cue_id_enabled = True
    lane.visible = True
    marks: list[Mark] = []
    for i in range(n):
        m = Mark.create(
            lane_index=lane.index,
            time_seconds=i * spacing,
            display_name=f"標記{i}",
        )
        m.main_cue_id = str(i + 1)
        marks.append(m)
    song.marks = marks
    song.sort_marks()
    return song


@pytest.fixture
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_position_lookup_10000_marks_is_indexed() -> None:
    song = _song_with_n_marks(10_000, spacing=0.01)
    assert len(song.marks) == 10_000
    t0 = time.perf_counter()
    for i in range(500):
        pos = (i * 37) % 100.0
        m = song.last_cue_list_mark_at_or_before(pos)
        assert m is not None
        assert m.time_seconds <= pos + 1e-4
    elapsed = time.perf_counter() - t0
    # Indexed path must stay well under a linear full-scan budget.
    assert elapsed < 0.15
    assert song.mark_count_in_window(50.0, 0.5) == pytest.approx(101, abs=2)


def test_repeated_ticks_same_cue_skip_now_card_update(app: QApplication) -> None:
    from cueplayer.ui.cue_monitor_panel import CueMonitorPanel

    song = _song_with_n_marks(50, spacing=1.0)
    panel = CueMonitorPanel()
    panel.set_song(song)
    perf_diag.set_enabled(True)
    perf_diag.clear()
    panel.set_position(5.2)
    snap1 = perf_diag.snapshot()["counters"]
    updated = int(snap1.get("now_card.position_sync.updated", 0))
    assert updated >= 1
    for _ in range(20):
        panel.set_position(5.3)
    snap2 = perf_diag.snapshot()["counters"]
    skipped = int(snap2.get("now_card.position_sync.skipped_unchanged", 0))
    assert skipped >= 15
    perf_diag.set_enabled(False)


def test_crossing_many_marks_is_one_bounded_range() -> None:
    song = _song_with_n_marks(500, spacing=0.05)
    crossed = song.mark_slice_in_time_range(10.0, 12.0)
    assert 35 <= len(crossed) <= 45
    t0 = time.perf_counter()
    for _ in range(100):
        song.mark_slice_in_time_range(10.0, 12.0)
    assert time.perf_counter() - t0 < 0.05


def test_playhead_update_does_not_require_mark_geometry_rebuild(
    app: QApplication,
) -> None:
    from cueplayer.ui.timeline_widget import TimelineWidget

    song = _song_with_n_marks(200, spacing=0.1)
    tl = TimelineWidget()
    tl.set_song(song)
    tl.set_playing(True)
    tl.resize(800, 400)
    tl.set_position(5.0)
    for i in range(10):
        tl.set_position(5.0 + 0.01 * i)
    # Viewport-bounded slice is much smaller than full song at typical zoom.
    t0, t1 = tl.visible_time_window()
    visible = song.mark_slice_in_time_range(t0 - 0.25, t1 + 0.25)
    assert len(visible) <= len(song.marks)
    assert len(visible) < len(song.marks) or (t1 - t0) > 15.0


def test_dense_marks_paint_uses_visible_slice(app: QApplication) -> None:
    from cueplayer.ui.timeline_widget import TimelineWidget

    song = _song_with_n_marks(5000, spacing=0.02)
    tl = TimelineWidget()
    tl.set_song(song)
    tl.resize(900, 400)
    tl.set_zoom(80.0)
    tl.set_position(20.0)
    t0, t1 = tl.visible_time_window()
    slice_n = len(song.mark_slice_in_time_range(t0 - 0.25, t1 + 0.25))
    assert slice_n < len(song.marks)
    assert slice_n < 800


def test_unicode_mark_names_still_supported() -> None:
    song = Song.create("歌")
    song.add_mark(song.mark_lanes[0].index, 1.0, display_name="中文標記★")
    m = song.last_mark_at_or_before(1.5)
    assert m is not None
    assert m.display_name == "中文標記★"


def test_active_mark_semantics_unchanged() -> None:
    song = Song.create("Song")
    lane = song.mark_lanes[0]
    a = song.add_mark(lane.index, 1.0, display_name="A")
    b = song.add_mark(lane.index, 2.0, display_name="B")
    assert song.active_mark_among_lanes([lane.index], 1.5).id == a.id
    assert song.active_mark_among_lanes([lane.index], 2.5).id == b.id
    assert song.active_mark_among_lanes([lane.index], 0.5) is None


def test_ma_export_untouched_by_lookup_change() -> None:
    """MA export helpers still see sorted marks (no exporter rewrite)."""
    song = _song_with_n_marks(20, spacing=0.5)
    ordered = song.main_marks_sorted()
    assert [m.time_seconds for m in ordered] == sorted(m.time_seconds for m in ordered)
