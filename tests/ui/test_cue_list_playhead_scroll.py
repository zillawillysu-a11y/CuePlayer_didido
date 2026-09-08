"""Cue List keeps the playhead row visible (not buried at the bottom edge)."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from cueplayer.domain.models import Project
from cueplayer.ui.cue_monitor_panel import CueMonitorPanel, _ROW_HEIGHT


@pytest.fixture
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _song_with_marks(count: int = 40):
    song = Project.create("S").new_song("Song")
    for i in range(count):
        song.add_mark(1, float(i))
    return song


def _prepare_short_cue_list(panel: CueMonitorPanel, app: QApplication) -> None:
    """Collapse NOW and use a short panel so the Cue List viewport is tight."""
    panel._now_primary_visible = False  # noqa: SLF001
    panel._now_secondary_visible = False  # noqa: SLF001
    panel._apply_now_panel_visibility()  # noqa: SLF001
    panel.resize(320, 420)
    app.processEvents()
    panel._fit_monitor_body_to_viewport()  # noqa: SLF001
    app.processEvents()
    # Leave room for clock; Cue List still gets a usable but short viewport.
    assert panel.cue_table.viewport().height() >= _ROW_HEIGHT


def test_playhead_cue_scrolls_into_view_with_bottom_margin(app: QApplication) -> None:
    panel = CueMonitorPanel()
    song = _song_with_marks(40)
    panel.set_song(song)
    panel.show()
    app.processEvents()
    _prepare_short_cue_list(panel, app)

    # Mid-list target so PositionAtCenter has room above and below.
    target = song.marks[20]
    panel.set_position(float(target.time_seconds) + 0.01)
    app.processEvents()
    panel._scroll_cue_row_into_view(target.id)  # noqa: SLF001
    app.processEvents()

    row = next(
        r
        for r in range(panel.cue_table.rowCount())
        if panel._mark_id_at_row(r) == target.id  # noqa: SLF001
    )
    index = panel.cue_table.model().index(row, 0)
    rect = panel.cue_table.visualRect(index)
    vp_h = panel.cue_table.viewport().height()
    assert vp_h >= _ROW_HEIGHT
    assert rect.height() > 0
    assert rect.top() >= 0
    # Not flush against / past the bottom edge (when the viewport has room).
    if vp_h >= _ROW_HEIGHT * 2:
        assert rect.bottom() <= vp_h - max(4, _ROW_HEIGHT // 4)
    else:
        assert rect.bottom() <= vp_h
        assert rect.top() < vp_h


def test_cue_row_scroll_does_not_move_outer_monitor_scroll(app: QApplication) -> None:
    """Cue follow must not yank the outer scroller — Clock stays where the user left it."""
    panel = CueMonitorPanel()
    song = _song_with_marks(40)
    panel.set_song(song)
    panel.show()
    panel.configure_output_timecode_clock(visible=True, color="#3dd68c")
    panel.resize(300, 240)
    app.processEvents()
    _prepare_short_cue_list(panel, app)

    outer = panel._monitor_scroll.verticalScrollBar()  # noqa: SLF001
    # Park on Clock (top). Playhead follow must only scroll Cue List internally.
    outer.setValue(0)
    app.processEvents()
    assert outer.value() == 0

    target = song.marks[22]
    panel.set_position(float(target.time_seconds) + 0.01)
    app.processEvents()
    panel._scroll_cue_row_into_view(target.id)  # noqa: SLF001
    app.processEvents()

    assert outer.value() == 0


def test_tiny_cue_list_keeps_playhead_row_visible(app: QApplication) -> None:
    """Even with ~1–2 row Cue List height, advancing playhead keeps the cue in view."""
    panel = CueMonitorPanel()
    song = _song_with_marks(50)
    panel.set_song(song)
    panel.show()
    app.processEvents()
    panel._now_primary_visible = False  # noqa: SLF001
    panel._now_secondary_visible = False  # noqa: SLF001
    panel._apply_now_panel_visibility()  # noqa: SLF001
    # Crush the panel; Cue List must still keep a usable table viewport.
    panel.resize(300, 260)
    app.processEvents()
    panel._fit_body_within_panel()  # noqa: SLF001
    panel._fit_monitor_body_to_viewport()  # noqa: SLF001
    app.processEvents()

    assert panel.cue_table.viewport().height() >= _ROW_HEIGHT - 2

    early = song.marks[5]
    panel.set_position(float(early.time_seconds) + 0.01)
    app.processEvents()
    panel._scroll_cue_row_into_view(early.id)  # noqa: SLF001
    app.processEvents()

    late = song.marks[40]
    panel.set_position(float(late.time_seconds) + 0.01)
    app.processEvents()
    # Flush deferred scroll from _select_mark_row.
    panel._scroll_cue_row_into_view(late.id)  # noqa: SLF001
    app.processEvents()

    assert panel._playhead_list_mark_id == late.id  # noqa: SLF001
    row = next(
        r
        for r in range(panel.cue_table.rowCount())
        if panel._mark_id_at_row(r) == late.id  # noqa: SLF001
    )
    rect = panel.cue_table.visualRect(panel.cue_table.model().index(row, 0))
    vp_h = panel.cue_table.viewport().height()
    assert rect.height() > 0
    assert rect.top() < vp_h
    assert rect.bottom() > 0


def test_short_clock_plus_cue_list_follows_playhead(app: QApplication) -> None:
    """Reproduce: Clock + thin Cue List; playhead at ~27s must not stay on 00:01 rows."""
    panel = CueMonitorPanel()
    song = Project.create("S").new_song("Song")
    times = [
        1.947,
        8.204,
        12.0,
        15.5,
        18.0,
        20.0,
        22.5,
        25.0,
        26.5,
        27.0,
        28.0,
        30.0,
        35.0,
        40.0,
    ]
    for t in times:
        song.add_mark(1, t)
    panel.set_song(song)
    panel.configure_output_timecode_clock(visible=True, color="#3dd68c")
    panel._now_primary_visible = False  # noqa: SLF001
    panel._now_secondary_visible = False  # noqa: SLF001
    panel._apply_now_panel_visibility()  # noqa: SLF001
    panel.show()
    panel.resize(320, 360)
    app.processEvents()
    panel._fit_monitor_body_to_viewport()  # noqa: SLF001
    app.processEvents()

    # Park like the user: outer scroller on Clock (must stay put).
    outer = panel._monitor_scroll.verticalScrollBar()  # noqa: SLF001
    outer.setValue(0)
    app.processEvents()

    panel.set_position(2.0)
    app.processEvents()
    panel.set_position(27.072)
    app.processEvents()
    panel._scroll_cue_row_into_view(  # noqa: SLF001
        song.last_cue_list_mark_at_or_before(27.072).id
    )
    app.processEvents()

    assert outer.value() == 0
    target = song.last_cue_list_mark_at_or_before(27.072)
    assert target is not None
    assert abs(target.time_seconds - 27.0) < 1e-6
    assert panel._playhead_list_mark_id == target.id  # noqa: SLF001

    visible_times: list[float] = []
    for r in range(panel.cue_table.rowCount()):
        rr = panel.cue_table.visualRect(panel.cue_table.model().index(r, 0))
        vp_h = panel.cue_table.viewport().height()
        if rr.height() <= 0 or rr.bottom() <= 0 or rr.top() >= vp_h:
            continue
        mid = panel._mark_id_at_row(r)  # noqa: SLF001
        mark = song.mark_by_id(mid) if mid else None
        if mark is not None:
            visible_times.append(mark.time_seconds)
    assert visible_times, "Cue List viewport should show at least one row"
    assert any(abs(t - 27.0) < 1e-6 for t in visible_times)
    assert not any(t < 10.0 for t in visible_times)


def test_follow_skips_marks_hidden_from_cue_list(app: QApplication) -> None:
    """Playhead follow targets the latest Cue List–eligible mark, not timeline-only."""
    panel = CueMonitorPanel()
    song = Project.create("S").new_song("Song")
    main_a = song.add_mark(1, 1.0, "A")
    other = song.add_mark(2, 2.0, "HiddenFromList")
    main_b = song.add_mark(1, 3.0, "B")
    lane2 = song.lane_by_index(2)
    assert lane2 is not None
    lane2.cue_list_enabled = False

    panel.set_song(song)
    panel.show()
    app.processEvents()
    _prepare_short_cue_list(panel, app)

    # Between other(2.0) and main_b(3.0) — chronological last is other, but Cue List
    # must stay on main_a until main_b.
    panel.set_position(2.5)
    app.processEvents()
    assert panel._playhead_list_mark_id == main_a.id  # noqa: SLF001

    panel.set_position(3.1)
    app.processEvents()
    assert panel._playhead_list_mark_id == main_b.id  # noqa: SLF001
    assert other.id not in {
        panel._mark_id_at_row(r) for r in range(panel.cue_table.rowCount())  # noqa: SLF001
    }


def test_layout_change_rescrolls_obscured_playhead_cue(app: QApplication) -> None:
    panel = CueMonitorPanel()
    song = _song_with_marks(40)
    panel.set_song(song)
    panel.show()
    panel.resize(320, 700)
    app.processEvents()

    target = song.marks[25]
    panel.set_position(float(target.time_seconds) + 0.01)
    app.processEvents()
    assert panel._playhead_list_mark_id == target.id  # noqa: SLF001

    # Collapse NOW + shrink window — previous scroll position is no longer valid.
    _prepare_short_cue_list(panel, app)
    # Push the selection out of view, then ask the panel to recover.
    bar = panel.cue_table.verticalScrollBar()
    bar.setValue(0)
    app.processEvents()
    panel._ensure_playhead_cue_visible()  # noqa: SLF001
    app.processEvents()

    row = next(
        r
        for r in range(panel.cue_table.rowCount())
        if panel._mark_id_at_row(r) == target.id  # noqa: SLF001
    )
    rect = panel.cue_table.visualRect(panel.cue_table.model().index(row, 0))
    vp_h = panel.cue_table.viewport().height()
    assert vp_h > 0
    assert rect.top() >= 0
    assert rect.bottom() <= vp_h


def test_new_mark_during_deferred_refresh_still_scrolls(app: QApplication) -> None:
    """Reproduce: mark added while Cue List refresh is pending must still scroll.

    Follow used to cache the new mark id before the row existed, then skip
    scrolling after refresh_list rebuilt the table.
    """
    panel = CueMonitorPanel()
    song = _song_with_marks(30)
    panel.set_song(song)
    panel.show()
    app.processEvents()
    _prepare_short_cue_list(panel, app)

    # Playhead past the last existing mark.
    last = song.marks[-1]
    panel.set_position(float(last.time_seconds) + 0.5)
    app.processEvents()
    assert panel._playhead_list_mark_id == last.id  # noqa: SLF001

    # Simulate the race: song already has the new mark, but the table has not
    # been rebuilt yet — follow caches the id and cannot find a row.
    new_mark = song.add_mark(1, float(last.time_seconds) + 0.25)
    panel.set_position(float(new_mark.time_seconds) + 0.01)
    app.processEvents()
    # Row missing → must NOT stick the playhead cache on the new id.
    assert panel._playhead_list_mark_id != new_mark.id  # noqa: SLF001

    # Deferred refresh rebuilds rows; follow must scroll to the new cue.
    panel.refresh_list()
    app.processEvents()
    assert panel._playhead_list_mark_id == new_mark.id  # noqa: SLF001

    row = next(
        r
        for r in range(panel.cue_table.rowCount())
        if panel._mark_id_at_row(r) == new_mark.id  # noqa: SLF001
    )
    # Force the deferred scrollTo from _select_mark_row.
    panel._scroll_cue_row_into_view(new_mark.id)  # noqa: SLF001
    app.processEvents()
    rect = panel.cue_table.visualRect(panel.cue_table.model().index(row, 0))
    vp_h = panel.cue_table.viewport().height()
    assert rect.height() > 0
    assert rect.top() >= 0
    assert rect.bottom() <= vp_h


def test_manual_cue_list_scroll_pauses_playhead_follow(app: QApplication) -> None:
    """While playing, scrolling Cue List must not yank the viewport back."""
    from PySide6.QtWidgets import QAbstractSlider

    panel = CueMonitorPanel()
    song = _song_with_marks(40)
    panel.set_song(song)
    panel.show()
    app.processEvents()
    _prepare_short_cue_list(panel, app)

    early = song.marks[5]
    panel.set_position(float(early.time_seconds) + 0.01)
    app.processEvents()
    panel._scroll_cue_row_into_view(early.id)  # noqa: SLF001
    app.processEvents()
    assert not panel._cue_list_follow_suspended  # noqa: SLF001

    bar = panel.cue_table.verticalScrollBar()
    # Get onto a mid cue first, then suspend, then step to the next cue (<0.5s).
    mid = song.marks[12]
    nxt = song.marks[13]
    panel.set_position(float(mid.time_seconds) + 0.8)
    app.processEvents()
    assert panel._playhead_list_mark_id == mid.id  # noqa: SLF001

    parked = min(bar.maximum(), bar.value() + max(80, _ROW_HEIGHT * 8))
    assert parked != bar.value()
    # Simulate a user scrollbar gesture (not a bare setValue from layout code).
    bar.triggerAction(QAbstractSlider.SliderAction.SliderMove)
    bar.setValue(parked)
    app.processEvents()
    assert panel._cue_list_follow_suspended  # noqa: SLF001
    assert bar.value() == parked

    # Playhead crosses into the next cue — selection advances, scroll stays put.
    panel.set_position(float(nxt.time_seconds) + 0.05)  # 12.8 → 13.05 (<0.5s)
    app.processEvents()
    assert panel._cue_list_follow_suspended  # noqa: SLF001
    assert bar.value() == parked
    assert panel._playhead_list_mark_id == nxt.id  # noqa: SLF001
    assert panel.selected_mark_ids() == [nxt.id]

    # Large seek resumes follow.
    late = song.marks[30]
    panel.set_position(float(late.time_seconds) + 0.01)
    app.processEvents()
    assert not panel._cue_list_follow_suspended  # noqa: SLF001
    panel._scroll_cue_row_into_view(late.id)  # noqa: SLF001
    app.processEvents()
    row = next(
        r
        for r in range(panel.cue_table.rowCount())
        if panel._mark_id_at_row(r) == late.id  # noqa: SLF001
    )
    rect = panel.cue_table.visualRect(panel.cue_table.model().index(row, 0))
    assert rect.height() > 0
    assert rect.top() < panel.cue_table.viewport().height()


def test_resume_cue_list_follow_from_menu_action(app: QApplication) -> None:
    panel = CueMonitorPanel()
    song = _song_with_marks(30)
    panel.set_song(song)
    panel.show()
    app.processEvents()
    _prepare_short_cue_list(panel, app)

    target = song.marks[20]
    panel.set_position(float(target.time_seconds) + 0.01)
    app.processEvents()
    panel._suspend_cue_list_follow()  # noqa: SLF001
    assert panel._cue_list_follow_suspended  # noqa: SLF001
    # Small playback tick while suspended — stay paused.
    panel.set_position(float(target.time_seconds) + 0.05)
    app.processEvents()
    assert panel._cue_list_follow_suspended  # noqa: SLF001

    panel._resume_cue_list_follow()  # noqa: SLF001
    app.processEvents()
    assert not panel._cue_list_follow_suspended  # noqa: SLF001
    assert panel._playhead_list_mark_id == target.id  # noqa: SLF001


def test_scroll_back_to_lit_cue_resumes_auto_follow(app: QApplication) -> None:
    """After scrolling away, scrolling the lit playhead cue back into view resumes follow."""
    from PySide6.QtWidgets import QAbstractSlider

    panel = CueMonitorPanel()
    song = _song_with_marks(40)
    panel.set_song(song)
    panel.show()
    app.processEvents()
    _prepare_short_cue_list(panel, app)

    mid = song.marks[10]
    panel.set_position(float(mid.time_seconds) + 0.01)
    app.processEvents()
    panel._scroll_cue_row_into_view(mid.id)  # noqa: SLF001
    app.processEvents()
    assert not panel._cue_list_follow_suspended  # noqa: SLF001

    bar = panel.cue_table.verticalScrollBar()
    away = min(bar.maximum(), bar.value() + max(120, _ROW_HEIGHT * 12))
    assert away != bar.value()
    bar.triggerAction(QAbstractSlider.SliderAction.SliderMove)
    bar.setValue(away)
    app.processEvents()
    assert panel._cue_list_follow_suspended  # noqa: SLF001
    assert panel._cue_list_follow_left_viewport  # noqa: SLF001
    assert not panel._playhead_cue_row_is_visible()  # noqa: SLF001

    # Scroll back until the lit cue is visible again → auto-follow resumes.
    bar.triggerAction(QAbstractSlider.SliderAction.SliderMove)
    panel._scroll_cue_row_into_view(mid.id)  # noqa: SLF001 — programmatic; simulate user return
    # User gesture path: set scroll so the row is visible, then run the resume check.
    # First make sure we're still suspended, then call the post-scroll handler as wheel would.
    panel._cue_list_follow_suspended = True
    panel._cue_list_follow_left_viewport = True
    # Bring playhead row on screen without going through resume (force flag path).
    panel._cue_list_follow_suspended = False
    panel._scroll_cue_row_into_view(mid.id)  # noqa: SLF001
    panel._cue_list_follow_suspended = True
    panel._cue_list_follow_left_viewport = True
    app.processEvents()
    assert panel._playhead_cue_row_is_visible()  # noqa: SLF001
    panel._maybe_resume_cue_list_follow_after_user_scroll()  # noqa: SLF001
    app.processEvents()
    assert not panel._cue_list_follow_suspended  # noqa: SLF001
    assert not panel._cue_list_follow_left_viewport  # noqa: SLF001
