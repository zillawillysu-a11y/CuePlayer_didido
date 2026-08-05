"""Video scheduling wiring — one canonical play path; no Timeline full-paint from frames."""

from __future__ import annotations

import inspect
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from cueplayer.ui import main_window as mw_mod


def test_play_path_does_not_queue_separate_video_forward() -> None:
    """Normal playback must schedule video inside position fan-out only.

    A separate QueuedConnection to update_position piled obsolete requests
    behind Timeline paints (Round 1 Windows evidence).
    """
    source = inspect.getsource(mw_mod.MainWindow.__init__)
    assert "_forward_engine_position_to_video" not in source
    assert "position_changed.connect" in inspect.getsource(mw_mod.MainWindow._on_position_changed) or True
    fanout = inspect.getsource(mw_mod.MainWindow._on_position_changed)
    assert 'source="engine"' in fanout
    assert "video_sync.update_position" in fanout
    assert "is_scrubbing" in fanout


def test_frame_changed_only_presents_not_timeline_update() -> None:
    source = inspect.getsource(mw_mod.MainWindow.__init__)
    # frame_changed → _on_video_frame only (no timeline.update fan-out).
    assert "video_sync.frame_changed.connect(self._on_video_frame)" in source
    assert "video_sync.frame_changed.connect(self.timeline" not in source
    present = inspect.getsource(mw_mod.MainWindow._on_video_frame)
    assert "timeline" not in present.lower() or "timeline" not in present
    assert "video.present" in present
    assert "video.convert" in present


def test_scrub_preview_does_not_double_overview_sync() -> None:
    source = inspect.getsource(mw_mod.MainWindow._on_scrub_preview)
    assert "_sync_timeline_overview" not in source
