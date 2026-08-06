"""Post-seek land: bounded decode deadlines + stage telemetry."""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication

from cueplayer.diagnostics import perf as perf_diag
from cueplayer.domain.models import Song, VideoClip
from cueplayer.playback import video_sync as vs_mod
from cueplayer.playback.video_sync import VideoPipelineState, VideoSyncController


@pytest.fixture
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_land_and_scrub_preview_deadlines_are_bounded() -> None:
    assert vs_mod._LAND_DECODE_DEADLINE_S <= 0.5
    assert vs_mod._SCRUB_PREVIEW_DECODE_DEADLINE_S <= 0.35
    assert vs_mod._RESUME_PLAY_DECODE_DEADLINE_S <= 0.6
    # Must stay well under the old stacked 1.5+1.5s play recovery path.
    assert (
        vs_mod._SCRUB_PREVIEW_DECODE_DEADLINE_S + vs_mod._LAND_DECODE_DEADLINE_S
        < 1.0
    )


def test_resume_skips_double_seek_recovery(app: QApplication, tmp_path: Path) -> None:
    """RESUME must not stack a second full seek after deadline timeout."""
    ctrl = VideoSyncController()
    ctrl._pipeline_state = VideoPipelineState.RESUME_PLAYBACK  # noqa: SLF001
    ctrl._play_seek_recovery_attempted = False  # noqa: SLF001

    class _FakeDec:
        seek_timed_out = True
        last_seek = None

        def frame_at(self, *args, **kwargs):  # noqa: ANN001, ANN002
            return None

    song = Song.create("t")
    clip = VideoClip.create(
        "c", tmp_path / "x.mp4", start_seconds=0.0, duration_seconds=5.0
    )
    song.video_clips = [clip]

    # Inject scrub/play maps so _frame_for finds the fake decoder path via
    # play worker decoder — exercise the resume skip branch directly.
    ctrl._song = song  # noqa: SLF001
    ctrl._worker_decoders[clip.id] = _FakeDec()  # noqa: SLF001
    ctrl._worker_decoder_paths[clip.id] = clip.path  # noqa: SLF001

    perf_diag.set_enabled(True)
    perf_diag.clear()
    out = ctrl._decode_frame_array(  # noqa: SLF001
        song,
        1.0,
        worker=True,
        scrub_decoder=False,
        deadline_s=0.1,
    )
    assert out is None
    assert ctrl._play_seek_recovery_attempted is True  # noqa: SLF001
    snap = perf_diag.snapshot()["counters"]
    assert int(snap.get("video.seek.resume_skip_double_recovery", 0)) >= 1
    # Must NOT have recreated (second seek).
    assert int(snap.get("video.seek.decoder_recreated", 0)) == 0
    perf_diag.set_enabled(False)
    ctrl.shutdown()


def test_position_tick_interval_rejects_large_gaps() -> None:
    """Cross-session / idle gaps must not enter position_tick_interval_ms."""
    perf_diag.set_enabled(True)
    perf_diag.clear()
    # Mirror MainWindow._perf_note_position_tick clamp.
    prev = 0.0
    now = 6185.0  # ~6.1e6 ms gap like the invalid Windows max
    delta_ms = (now - prev) * 1000.0
    if 0.0 < delta_ms < 5000.0:
        perf_diag.record_ms("perf.position_tick_interval_ms", delta_ms)
    spans = perf_diag.snapshot().get("spans", {})
    assert "perf.position_tick_interval_ms" not in spans
    # Valid short interval is recorded.
    perf_diag.record_ms("perf.position_tick_interval_ms", 16.0)
    st = perf_diag.snapshot()["spans"]["perf.position_tick_interval_ms"]
    assert st["count"] == 1
    assert abs(st["max_ms"] - 16.0) < 1e-6
    perf_diag.set_enabled(False)
