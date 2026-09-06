"""Regression: LTC Clips lane must appear on first Song hydration, not only
after a manual Source toggle.

A Song persisted with ``ltc_source_mode = "clip_generator"`` was showing an
empty timeline (no LTC Clips lane) the first time it loaded after reopening
the project — the lane only appeared after the user manually switched the
Source menu away from and back to Clip Generator. Root cause: MainWindow's
initial ``TimelineWidget.set_song`` call (both at MainWindow construction and
via ``ShowSessionService.activate_song_at`` → ``refresh_timeline``) never
pushed the resolved per-song LTC source mode into the timeline widget — that
push only happened as a side effect of ``_apply_loaded_audio`` finishing,
which never runs for a song with no main audio file (the common case for a
Clip Generator song). ``TimelineWidget`` itself defaults to source mode
"off", so the lane silently stayed invisible until a manual
``set_ltc_source_mode`` call (Source menu, or a song switch that happened to
have a resolvable main audio file) finally synced it.

The fix makes ``ShowSessionService.refresh_timeline`` (the single function
now shared by MainWindow construction and every later song activate) push
the resolved mode synchronously, right after ``set_song`` — independent of
whether/when audio loads.
"""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from cueplayer.domain.models import Project, Song
from cueplayer.ui.main_window import MainWindow


@pytest.fixture
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _project_with_song(mode: str) -> Project:
    project = Project.create("Hydration", with_song=False)
    song = Song.create("No Audio Song")
    song.ltc_source_mode = mode
    # No audio_tracks / video_clips — mirrors a Clip Generator-only song with
    # no main audio file, the path that skipped the LTC-mode push entirely.
    project.songs = [song]
    return project


@pytest.mark.parametrize(
    ("mode", "expect_lane"),
    [
        ("clip_generator", True),
        ("full_track_generator", False),
        ("striped_file", False),
        ("off", False),
    ],
)
def test_initial_hydration_matches_resolved_mode(
    app: QApplication, mode: str, expect_lane: bool
) -> None:
    project = _project_with_song(mode)
    window = MainWindow(project)
    try:
        # First bind only — no source toggle, no song switch.
        assert window.timeline._ltc_clip_lane_active() is expect_lane, (
            f"mode={mode!r} must {'show' if expect_lane else 'hide'} the LTC "
            "Clips lane immediately on first Song hydration"
        )
    finally:
        window.close()


def test_refresh_timeline_hydrates_clip_generator_lane_without_manual_toggle(
    app: QApplication,
) -> None:
    """Same invariant via the shared runtime refresh path (``refresh_timeline``).

    ``ShowSessionService.refresh_timeline`` is the exact function
    ``activate_song_at`` (song switch / project restore) calls to re-bind the
    timeline — exercised directly here rather than through the full
    ``_activate_song`` orchestration (engine stop/quiesce, PortAudio) which
    needs a real or mocked output device and is out of scope for this
    UI-hydration regression.
    """
    project = Project.create("Hydration", with_song=False)
    plain = Song.create("Plain Song")
    plain.ltc_source_mode = "off"
    clip_song = Song.create("Clip Generator Song")
    clip_song.ltc_source_mode = "clip_generator"
    project.songs = [plain, clip_song]

    window = MainWindow(project)
    try:
        assert window.timeline._ltc_clip_lane_active() is False
        window.current_song = clip_song
        window.show_session.refresh_timeline()
        assert window.timeline._ltc_clip_lane_active() is True, (
            "refresh_timeline must show the LTC Clips lane for a "
            "clip_generator song without any explicit set_ltc_source_mode "
            "toggle"
        )
    finally:
        window.close()
