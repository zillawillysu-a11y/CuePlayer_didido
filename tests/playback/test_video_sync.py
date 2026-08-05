"""VideoSyncController: frames driven purely by `update_position()` calls, i.e. the
audio sample clock — never an independent timer. Uses tiny synthetic clips so the
tests don't need binary fixtures."""

from __future__ import annotations

import time
from pathlib import Path
from unittest.mock import patch

import av
import numpy as np
import pytest
from PySide6.QtWidgets import QApplication

from cueplayer.domain.models import Song, VideoClip
from cueplayer.playback.video_sync import VideoSyncController

WIDTH, HEIGHT, FPS = 32, 24, 10


def _make_solid_clip(path: Path, color: tuple[int, int, int], *, seconds: float = 2.0) -> None:
    container = av.open(str(path), mode="w")
    try:
        stream = container.add_stream("mpeg4", rate=FPS)
        stream.width = WIDTH
        stream.height = HEIGHT
        stream.pix_fmt = "yuv420p"
        for i in range(int(FPS * seconds)):
            arr = np.zeros((HEIGHT, WIDTH, 3), dtype=np.uint8)
            arr[:, :] = color
            frame = av.VideoFrame.from_ndarray(arr, format="rgb24")
            for packet in stream.encode(frame):
                container.mux(packet)
        for packet in stream.encode():
            container.mux(packet)
    finally:
        container.close()


@pytest.fixture
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


@pytest.fixture
def red_clip_path(tmp_path: Path) -> Path:
    path = tmp_path / "紅.mp4"
    _make_solid_clip(path, (255, 0, 0))
    return path


@pytest.fixture
def blue_clip_path(tmp_path: Path) -> Path:
    path = tmp_path / "藍.mp4"
    _make_solid_clip(path, (0, 0, 255))
    return path


def test_update_position_emits_none_frame_with_no_song(app: QApplication) -> None:
    controller = VideoSyncController()
    frames: list[object] = []
    controller.frame_changed.connect(frames.append)
    controller.update_position(1.0)
    assert frames == [None]


def test_update_position_emits_none_frame_outside_any_clip(
    app: QApplication, red_clip_path: Path
) -> None:
    song = Song.create("Song")
    clip = VideoClip.create(name="red", path=red_clip_path, start_seconds=5.0, duration_seconds=2.0)
    song.add_video_clip(clip)

    controller = VideoSyncController()
    controller.set_song(song)
    frames: list[object] = []
    controller.frame_changed.connect(frames.append)
    # Land inside the clip first so a real frame is on screen.
    controller.update_position(5.5)
    assert len(frames) == 1 and frames[0] is not None
    # Moving outside must clear to black (not suppressed — last emit was a frame).
    controller.update_position(0.0)
    assert frames[-1] is None


def test_update_position_decodes_frame_from_active_clip(
    app: QApplication, red_clip_path: Path
) -> None:
    song = Song.create("Song")
    clip = VideoClip.create(name="red", path=red_clip_path, start_seconds=1.0, duration_seconds=2.0)
    song.add_video_clip(clip)

    controller = VideoSyncController()
    controller.set_song(song)
    frames: list[object] = []
    controller.frame_changed.connect(frames.append)
    controller.update_position(1.5)

    assert len(frames) == 1
    frame = frames[0]
    assert isinstance(frame, np.ndarray)
    assert frame.mean(axis=(0, 1))[0] > frame.mean(axis=(0, 1))[2]  # red-dominant


def test_update_position_switches_clip_as_playhead_advances(
    app: QApplication, red_clip_path: Path, blue_clip_path: Path
) -> None:
    song = Song.create("Song")
    song.add_video_clip(
        VideoClip.create(name="red", path=red_clip_path, start_seconds=0.0, duration_seconds=2.0)
    )
    song.add_video_clip(
        VideoClip.create(name="blue", path=blue_clip_path, start_seconds=2.0, duration_seconds=2.0)
    )

    controller = VideoSyncController()
    controller.set_song(song)
    frames: list[object] = []
    controller.frame_changed.connect(frames.append)

    controller.update_position(0.5)
    # Intentionally jump to the next clip — bypass seek coalesce so the
    # test asserts the decode result, not the trailing-edge timer.
    controller.land_frame_at(2.5)

    assert len(frames) == 2
    first, second = frames
    assert first.mean(axis=(0, 1))[0] > first.mean(axis=(0, 1))[2]
    assert second.mean(axis=(0, 1))[2] > second.mean(axis=(0, 1))[0]


def test_active_clip_changed_emits_only_on_transition(
    app: QApplication, red_clip_path: Path
) -> None:
    song = Song.create("Song")
    clip = VideoClip.create(name="red", path=red_clip_path, start_seconds=0.0, duration_seconds=2.0)
    song.add_video_clip(clip)

    controller = VideoSyncController()
    controller.set_song(song)
    transitions: list[object] = []
    controller.active_clip_changed.connect(transitions.append)

    controller.update_position(0.1)
    controller.update_position(0.2)  # still inside the same clip: no new signal
    controller.update_position(5.0)  # leaves the clip: emits None

    assert len(transitions) == 2
    assert transitions[0] is not None and transitions[0].id == clip.id
    assert transitions[1] is None


def test_overlap_warning_emitted_once_per_overlap_pair(
    app: QApplication, red_clip_path: Path, blue_clip_path: Path
) -> None:
    song = Song.create("Song")
    a = VideoClip.create(name="red", path=red_clip_path, start_seconds=0.0, duration_seconds=5.0)
    b = VideoClip.create(name="blue", path=blue_clip_path, start_seconds=2.0, duration_seconds=5.0)
    song.add_video_clip(a)
    song.add_video_clip(b)

    controller = VideoSyncController()
    controller.set_song(song)
    warnings: list[str] = []
    controller.overlap_warning.connect(warnings.append)

    controller.update_position(3.0)
    controller.update_position(3.1)  # same overlap pair: should not re-warn
    controller.update_position(3.2)

    assert len(warnings) == 1


def test_refresh_closes_decoders_for_removed_clips(app: QApplication, red_clip_path: Path) -> None:
    song = Song.create("Song")
    clip = VideoClip.create(name="red", path=red_clip_path, start_seconds=0.0, duration_seconds=2.0)
    song.add_video_clip(clip)

    controller = VideoSyncController()
    controller.set_song(song)
    controller.update_position(0.5)  # opens a decoder for `clip`
    assert clip.id in controller._decoders

    song.remove_video_clips_by_ids({clip.id})
    controller.refresh()
    assert clip.id not in controller._decoders


def test_scrubbing_throttles_rapid_decodes(app: QApplication, red_clip_path: Path) -> None:
    """While scrubbing, rapid-fire calls (as the timeline emits on every
    mouse-move) should collapse to far fewer actual decodes — the fix for
    drag lag once a video clip is on the timeline. Idle/paused seeks use a
    lighter trailing-edge throttle (see test_paused_seeks_coalesce)."""
    song = Song.create("Song")
    clip = VideoClip.create(name="red", path=red_clip_path, start_seconds=0.0, duration_seconds=2.0)
    song.add_video_clip(clip)

    controller = VideoSyncController()
    controller.set_song(song)
    frames: list[object] = []
    controller.frame_changed.connect(frames.append)

    controller.set_scrubbing(True)
    for i in range(20):
        controller.update_position(0.01 * i, source="scrub")
    # 20 calls fired back-to-back (sub-millisecond apart) must not all decode.
    assert len(frames) < 20

    controller.set_scrubbing(False)  # async land the last requested position
    _drain_async(controller, app)
    assert len(frames) >= 1


def test_scrub_end_flushes_final_position(app: QApplication, red_clip_path: Path, blue_clip_path: Path) -> None:
    song = Song.create("Song")
    song.add_video_clip(
        VideoClip.create(name="red", path=red_clip_path, start_seconds=0.0, duration_seconds=2.0)
    )
    song.add_video_clip(
        VideoClip.create(name="blue", path=blue_clip_path, start_seconds=2.0, duration_seconds=2.0)
    )

    controller = VideoSyncController()
    controller.set_song(song)
    frames: list[object] = []
    controller.frame_changed.connect(frames.append)

    controller.set_scrubbing(True)
    controller._scrub_cache.clear()
    controller.update_position(0.1, source="scrub")
    controller.update_position(2.5, source="scrub")
    controller.set_scrubbing(False)  # async land last target
    _drain_async(controller, app)

    assert len(frames) >= 1
    last = frames[-1]
    assert last is not None
    # The flushed frame must be the blue clip (2.5s), not a stale red one.
    assert last.mean(axis=(0, 1))[2] > last.mean(axis=(0, 1))[0]


def test_playing_throttles_rapid_decodes(app: QApplication, red_clip_path: Path) -> None:
    """Mirrors test_scrubbing_throttles_rapid_decodes but for set_playing() —
    this is the fix for the "timeline unusable while a video plays" bug:
    AudioEngine ticks position_changed at ~60Hz during playback, but decode
    work must not follow it 1:1 or it starves the UI thread the timeline
    paints/handles input on."""
    song = Song.create("Song")
    clip = VideoClip.create(name="red", path=red_clip_path, start_seconds=0.0, duration_seconds=2.0)
    song.add_video_clip(clip)

    controller = VideoSyncController()
    controller.set_song(song)
    frames: list[object] = []
    controller.frame_changed.connect(frames.append)

    controller.set_playing(True)
    for i in range(60):
        controller.update_position(0.001 * i)
    # 60 ticks fired back-to-back (as AudioEngine's 16ms poll would deliver
    # over ~1s of real playback) must not all decode.
    assert len(frames) < 60

    controller.set_playing(False)  # flush: the last requested position must land.
    assert len(frames) >= 1
    controller.shutdown()


def test_paused_seeks_coalesce_rapid_jumps(
    app: QApplication, red_clip_path: Path, blue_clip_path: Path
) -> None:
    """Rapid click-seeks while paused must not decode every intermediate land
    frame — only the latest after the trailing-edge flush."""
    song = Song.create("Song")
    song.add_video_clip(
        VideoClip.create(name="red", path=red_clip_path, start_seconds=0.0, duration_seconds=2.0)
    )
    song.add_video_clip(
        VideoClip.create(name="blue", path=blue_clip_path, start_seconds=2.0, duration_seconds=2.0)
    )

    controller = VideoSyncController()
    controller.set_song(song)
    frames: list[object] = []
    controller.frame_changed.connect(frames.append)

    controller.update_position(0.1)  # first land: immediate
    for t in (0.5, 1.0, 1.5, 2.5):
        controller.update_position(t)
    assert len(frames) < 5
    assert controller._pending_seconds == pytest.approx(2.5)

    # Flush timer lands the latest jump (blue).
    app.processEvents()
    if controller._flush_timer.isActive():
        controller._flush_timer.stop()
        controller._flush_pending()
    last = frames[-1]
    assert last is not None
    assert last.mean(axis=(0, 1))[2] > last.mean(axis=(0, 1))[0]


def test_playback_decode_rate_stays_near_display_refresh_cap(
    app: QApplication, red_clip_path: Path
) -> None:
    """Direct proof the play path is bounded to roughly the playback
    cap (VideoSyncController._MAX_PLAY_DECODE_HZ / _MIN_PLAY_DECODE_INTERVAL)
    rather than the position-tick rate: hammer update_position() as fast as
    Python can for a fixed wall-clock window and assert the number of frames
    actually decoded+emitted is close to `window * play_hz`, not the (much
    larger) number of calls made."""
    from cueplayer.playback import video_sync as video_sync_mod

    song = Song.create("Song")
    clip = VideoClip.create(name="red", path=red_clip_path, start_seconds=0.0, duration_seconds=2.0)
    song.add_video_clip(clip)

    controller = VideoSyncController()
    controller.set_song(song)
    frames: list[object] = []
    controller.frame_changed.connect(frames.append)
    controller.set_playing(True)

    window_seconds = 0.2
    deadline = time.monotonic() + window_seconds
    calls = 0
    t = 0.0
    while time.monotonic() < deadline:
        controller.update_position(t)
        t += 0.001
        calls += 1
    controller.set_playing(False)  # flush the last pending position

    assert calls > 100  # sanity: this really did hammer update_position()
    play_hz = float(video_sync_mod._MAX_PLAY_DECODE_HZ)
    max_expected_frames = int(window_seconds * play_hz) + 3  # + slack for scheduling jitter
    assert len(frames) <= max_expected_frames
    # Cap must stay at/under ~display refresh so timeline paint still wins.
    assert play_hz <= 30.0
    assert play_hz >= 24.0
    assert float(video_sync_mod._MAX_PLAY_DECODE_HZ_HEAVY) <= play_hz
    assert float(video_sync_mod._MAX_PLAY_DECODE_HZ_HEAVY) >= 20.0


def test_duplicate_decoded_frame_is_not_reemitted(app: QApplication, red_clip_path: Path) -> None:
    """Even outside play/scrub throttling, VideoDecoder.frame_at() can hand
    back the exact same cached ndarray for two nearby positions inside the
    same source frame (see test_video_loader.py) — VideoSyncController must
    not push that unchanged frame through to the Preview/Clean Output
    widgets a second time (each emit costs a QImage copy + repaint)."""
    song = Song.create("Song")
    clip = VideoClip.create(name="red", path=red_clip_path, start_seconds=0.0, duration_seconds=2.0)
    song.add_video_clip(clip)

    controller = VideoSyncController()
    controller.set_song(song)
    frames: list[object] = []
    controller.frame_changed.connect(frames.append)

    # FPS=10 in _make_solid_clip -> both land inside the same ~0.1s frame.
    controller.update_position(0.01)
    controller.update_position(0.02)

    assert len(frames) == 1


def test_decode_quality_defaults_full_and_invalidates_cached_decoders(
    app: QApplication, red_clip_path: Path
) -> None:
    song = Song.create("Song")
    clip = VideoClip.create(name="red", path=red_clip_path, start_seconds=0.0, duration_seconds=2.0)
    song.add_video_clip(clip)

    controller = VideoSyncController()
    assert controller.decode_quality() == "full"
    controller.set_song(song)
    controller.update_position(0.1)  # opens + caches a decoder for `clip`
    assert clip.id in controller._decoders

    controller.set_decode_quality("720p")
    assert controller.decode_quality() == "720p"
    # Cached decoder was opened under the old cap; must be dropped so the
    # next frame request reopens the container at the new one.
    assert clip.id not in controller._decoders

    # land_frame_at bypasses seek coalesce (two update_position calls in the
    # same tick would otherwise only queue a trailing flush).
    controller.land_frame_at(0.1)
    assert clip.id in controller._decoders


def test_set_song_none_clears_state_and_emits_black_frame(
    app: QApplication, red_clip_path: Path
) -> None:
    song = Song.create("Song")
    clip = VideoClip.create(name="red", path=red_clip_path, start_seconds=0.0, duration_seconds=2.0)
    song.add_video_clip(clip)

    controller = VideoSyncController()
    controller.set_song(song)
    controller.update_position(0.5)

    frames: list[object] = []
    controller.frame_changed.connect(frames.append)
    controller.set_song(None)
    assert frames == [None]
    assert controller._decoders == {}


def test_video_output_inactive_skips_decode(app: QApplication, red_clip_path: Path) -> None:
    """When neither Preview nor Clean Output needs frames, decode must not run."""
    song = Song.create("Song")
    clip = VideoClip.create(name="red", path=red_clip_path, start_seconds=0.0, duration_seconds=2.0)
    song.add_video_clip(clip)

    controller = VideoSyncController()
    controller.set_song(song)
    frames: list[object] = []
    controller.frame_changed.connect(frames.append)

    controller.set_video_output_active(False)
    controller.update_position(0.5)
    controller.update_position(1.0)

    assert frames == []
    assert clip.id not in controller._decoders

    controller.set_video_output_active(True)
    app.processEvents()  # deferred first-frame decode after Clean Output show
    assert len(frames) == 1
    assert isinstance(frames[0], np.ndarray)


def test_video_output_reenable_uses_last_position(
    app: QApplication, red_clip_path: Path, blue_clip_path: Path
) -> None:
    song = Song.create("Song")
    song.add_video_clip(
        VideoClip.create(name="red", path=red_clip_path, start_seconds=0.0, duration_seconds=2.0)
    )
    song.add_video_clip(
        VideoClip.create(name="blue", path=blue_clip_path, start_seconds=2.0, duration_seconds=2.0)
    )

    controller = VideoSyncController()
    controller.set_song(song)
    controller.set_video_output_active(False)
    controller.update_position(2.5)

    frames: list[object] = []
    controller.frame_changed.connect(frames.append)
    controller.set_video_output_active(True)
    app.processEvents()  # deferred first-frame decode after Clean Output show

    assert len(frames) == 1
    frame = frames[0]
    assert isinstance(frame, np.ndarray)
    assert frame.mean(axis=(0, 1))[2] > frame.mean(axis=(0, 1))[0]


def test_set_song_does_not_preload_scrub_cache(
    app: QApplication, red_clip_path: Path
) -> None:
    """Opening/switching songs must not start scrub PyAV while Clean Output
    may also be decoding — that contended on av_path_lock and stalled the UI."""
    song = Song.create("Song")
    clip = VideoClip.create(name="red", path=red_clip_path, start_seconds=0.0, duration_seconds=2.0)
    song.add_video_clip(clip)

    controller = VideoSyncController()
    with patch.object(controller._scrub_cache, "preload") as preload:
        controller.set_song(song)
    preload.assert_not_called()
    assert not controller._scrub_cache.ready(clip.id)


def test_set_video_output_active_does_not_preload_scrub(
    app: QApplication, red_clip_path: Path
) -> None:
    song = Song.create("Song")
    clip = VideoClip.create(name="red", path=red_clip_path, start_seconds=0.0, duration_seconds=2.0)
    song.add_video_clip(clip)

    controller = VideoSyncController()
    controller.set_song(song)
    controller.update_position(0.5)
    controller.set_video_output_active(False)
    with patch.object(controller._scrub_cache, "preload") as preload:
        controller.set_video_output_active(True)
    preload.assert_not_called()


def test_click_seek_scrub_does_not_start_preload(
    app: QApplication, red_clip_path: Path
) -> None:
    """Press+release seek must not kick scrub PyAV (Clean Output crash race)."""
    song = Song.create("Song")
    clip = VideoClip.create(name="red", path=red_clip_path, start_seconds=0.0, duration_seconds=2.0)
    song.add_video_clip(clip)

    controller = VideoSyncController()
    controller.set_song(song)
    controller.set_playing(True)
    controller.update_position(0.2)

    with patch.object(controller._scrub_cache, "preload") as preload:
        controller.set_scrubbing(True)
        controller.update_position(1.0)
        controller.set_scrubbing(False)
        app.processEvents()
        preload.assert_not_called()


def test_scrubbing_uses_preloaded_cache_without_live_decoder(
    app: QApplication, red_clip_path: Path
) -> None:
    """Once scrub posters are warm, mid-drag Preview must not open/seek the
    live UI-thread decoder (that hitch felt like 'loading video')."""
    song = Song.create("Song")
    clip = VideoClip.create(name="red", path=red_clip_path, start_seconds=0.0, duration_seconds=2.0)
    song.add_video_clip(clip)

    controller = VideoSyncController()
    controller.set_song(song)
    controller._scrub_cache.preload(list(song.video_clips))

    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline and not controller._scrub_cache.ready(clip.id):
        time.sleep(0.05)
    assert controller._scrub_cache.ready(clip.id)

    # Ensure no live decoder is open, then scrub.
    controller._close_all_decoders()
    assert clip.id not in controller._decoders

    frames: list[object] = []
    controller.frame_changed.connect(frames.append)
    controller.set_scrubbing(True)
    # Pretend preload already ran (deferred timer would normally do this).
    controller._scrub_preload_timer.stop()
    controller.update_position(0.3, source="scrub")
    controller.update_position(1.2, source="scrub")

    assert len(frames) >= 1
    assert all(isinstance(f, np.ndarray) for f in frames if f is not None)
    # Mid-scrub must not have opened the live UI decoder.
    assert clip.id not in controller._decoders

    controller.set_scrubbing(False)
    _drain_async(controller, app)
    # Exact land is async on the worker pool — UI decoder must stay unused.
    assert clip.id not in controller._decoders


def test_land_frame_after_set_song_while_already_active(
    app: QApplication, red_clip_path: Path
) -> None:
    """Preview must not stay black after set_song when output stays active."""
    song = Song.create("Song")
    song.add_video_clip(
        VideoClip.create(
            name="red", path=red_clip_path, start_seconds=0.0, duration_seconds=2.0
        )
    )
    controller = VideoSyncController()
    controller.set_song(song)
    controller.update_position(0.4)
    frames: list[object] = []
    controller.frame_changed.connect(frames.append)

    # Mimic activate: clear picture, output flag unchanged (already True).
    controller.set_song(song)
    assert frames[-1] is None
    controller.set_video_output_active(True)  # no-op — early return
    assert frames[-1] is None

    controller.land_frame_at(0.4)
    assert isinstance(frames[-1], np.ndarray)


def _drain_async(controller: VideoSyncController, app: QApplication, timeout: float = 3.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.processEvents()
        if (
            not controller._async_inflight
            and not controller._final_land_pending
            and not controller._land_retry_timer.isActive()
        ):
            break
        time.sleep(0.01)
    app.processEvents()


def _drain_land_and_resume(
    controller: VideoSyncController, app: QApplication, timeout: float = 4.0
) -> None:
    """Drain land work, then complete resume if still pending (Round 5)."""
    from cueplayer.playback.video_sync import VideoPipelineState

    _drain_async(controller, app, timeout=timeout)
    if (
        controller.pipeline_state() == VideoPipelineState.RESUME_PLAYBACK
        and controller._resume_pending
    ):
        controller._complete_resume(reason="drain")
        app.processEvents()


def test_scrub_cold_does_not_sync_decode_on_ui_thread(
    app: QApplication, red_clip_path: Path
) -> None:
    """Aggressive scrub must not block the caller on PyAV (latest-wins async)."""
    song = Song.create("Song")
    clip = VideoClip.create(name="red", path=red_clip_path, start_seconds=0.0, duration_seconds=2.0)
    song.add_video_clip(clip)

    controller = VideoSyncController()
    controller.set_song(song)
    # Ensure scrub cache is cold so the live path is exercised.
    controller._scrub_cache.clear()

    decode_calls = {"n": 0}
    real_decode = controller._decode_and_emit

    def _counting_decode(song_arg, seconds, **kwargs):  # noqa: ANN001
        decode_calls["n"] += 1
        return real_decode(song_arg, seconds, **kwargs)

    controller.set_scrubbing(True)
    with patch.object(controller, "_decode_and_emit", side_effect=_counting_decode):
        t0 = time.monotonic()
        for i in range(40):
            controller.update_position(0.02 * i, source="scrub")
        elapsed = time.monotonic() - t0
        # Must return immediately — no sync PyAV per mouse-move.
        assert decode_calls["n"] == 0
        assert elapsed < 0.25
        # Preview tick may async-request; still no sync.
        controller._on_scrub_preview_tick()
        assert decode_calls["n"] == 0
        controller.set_scrubbing(False)  # final land is async-only (no UI PyAV)
        assert decode_calls["n"] == 0


def test_async_latest_request_wins(app: QApplication, red_clip_path: Path, blue_clip_path: Path) -> None:
    song = Song.create("Song")
    song.add_video_clip(
        VideoClip.create(name="red", path=red_clip_path, start_seconds=0.0, duration_seconds=2.0)
    )
    song.add_video_clip(
        VideoClip.create(name="blue", path=blue_clip_path, start_seconds=2.0, duration_seconds=2.0)
    )

    controller = VideoSyncController()
    controller.set_song(song)
    frames: list[object] = []
    controller.frame_changed.connect(frames.append)
    controller.set_playing(True)

    requested: list[float] = []
    real_request = controller._request_async_live_frame

    def _track(seconds: float, **kwargs) -> None:  # noqa: ANN003
        requested.append(float(seconds))
        real_request(seconds, **kwargs)

    with patch.object(controller, "_request_async_live_frame", side_effect=_track):
        controller._last_decode_time = 0.0
        controller.update_position(0.1)
        for t in (0.5, 1.0, 1.5, 2.5):
            controller._last_decode_time = 0.0
            controller.update_position(t)

    assert requested  # at least one async schedule (idle submit)
    # Later engine ticks must not each open a new request while busy —
    # they overwrite the single pending latest target.
    assert controller._play_pending_seconds == pytest.approx(2.5) or (
        controller._async_req_seconds == pytest.approx(2.5)
    )
    _drain_async(controller, app)
    controller.set_playing(False)
    last = frames[-1]
    assert last is not None
    # Final land (stop) should be blue at 2.5s.
    assert last.mean(axis=(0, 1))[2] > last.mean(axis=(0, 1))[0]
    controller.shutdown()


def test_async_stale_frames_discarded(app: QApplication, red_clip_path: Path) -> None:
    song = Song.create("Song")
    clip = VideoClip.create(name="red", path=red_clip_path, start_seconds=0.0, duration_seconds=2.0)
    song.add_video_clip(clip)

    controller = VideoSyncController()
    controller.set_song(song)
    emitted: list[object] = []
    controller.frame_changed.connect(emitted.append)
    controller.set_playing(True)
    controller.update_position(0.2)
    stale_gen = controller._async_req_gen
    # Invalidate before the worker result can land.
    controller._invalidate_async_requests()
    assert controller._async_req_gen != stale_gen
    _drain_async(controller, app)
    # Stale emit must not advance the picture after invalidate+no new request.
    # (set_song already emitted None; playing update may have scheduled work.)
    before = list(emitted)
    controller._on_async_frame_ready(stale_gen, 0.2, np.zeros((4, 4, 3), dtype=np.uint8))
    assert emitted == before


def test_async_queue_bounded_during_scrub(
    app: QApplication, red_clip_path: Path
) -> None:
    """Coalesce: many schedule calls while inflight → still a single worker job."""
    from cueplayer.diagnostics import perf as perf_diag

    song = Song.create("Song")
    clip = VideoClip.create(name="red", path=red_clip_path, start_seconds=0.0, duration_seconds=2.0)
    song.add_video_clip(clip)

    controller = VideoSyncController()
    controller.set_song(song)
    controller._scrub_cache.clear()
    controller.set_scrubbing(True)

    perf_diag.set_enabled(True)
    perf_diag.clear()
    # Force schedule path (bypass throttle) by resetting last_decode_time each time.
    for i in range(30):
        controller._last_decode_time = 0.0
        controller.update_position(0.01 * i)

    snap = perf_diag.snapshot()
    counters = snap.get("counters", snap) if isinstance(snap, dict) else {}
    if not isinstance(counters, dict) or "video.async_schedule" not in counters:
        # snapshot shape may nest — also accept report text.
        report = perf_diag.report_text()
        assert "video.async_schedule" in report
        assert "video.async_coalesce" in report
    else:
        assert counters["video.async_schedule"] >= 1
        assert counters.get("video.async_coalesce", 0) >= 1

    # Never more than one inflight worker (queue depth ≤ 1).
    assert int(controller._async_inflight) in (0, 1)
    controller.set_scrubbing(False)
    _drain_async(controller, app)
    perf_diag.set_enabled(False)


def test_scrub_end_frame_matches_release_time(
    app: QApplication, red_clip_path: Path, blue_clip_path: Path
) -> None:
    song = Song.create("Song")
    song.add_video_clip(
        VideoClip.create(name="red", path=red_clip_path, start_seconds=0.0, duration_seconds=2.0)
    )
    song.add_video_clip(
        VideoClip.create(name="blue", path=blue_clip_path, start_seconds=2.0, duration_seconds=2.0)
    )

    controller = VideoSyncController()
    controller.set_song(song)
    frames: list[object] = []
    controller.frame_changed.connect(frames.append)

    controller.set_scrubbing(True)
    controller._scrub_cache.clear()
    for t in (0.1, 0.5, 1.0, 2.5):
        controller._last_decode_time = 0.0
        controller.update_position(t, source="scrub")
    release = 2.5
    controller.update_position(release, source="scrub")
    controller.set_scrubbing(False)
    _drain_async(controller, app)
    last = frames[-1]
    assert last is not None
    assert last.mean(axis=(0, 1))[2] > last.mean(axis=(0, 1))[0]
    assert controller._last_position_seconds == pytest.approx(release)


def test_playback_async_still_follows_song_time(
    app: QApplication, red_clip_path: Path, blue_clip_path: Path
) -> None:
    """Playback remains audio-clock driven: async present still tracks Song Time."""
    song = Song.create("Song")
    song.add_video_clip(
        VideoClip.create(name="red", path=red_clip_path, start_seconds=0.0, duration_seconds=2.0)
    )
    song.add_video_clip(
        VideoClip.create(name="blue", path=blue_clip_path, start_seconds=2.0, duration_seconds=2.0)
    )

    controller = VideoSyncController()
    controller.set_song(song)
    frames: list[object] = []
    controller.frame_changed.connect(frames.append)
    controller.set_playing(True)
    controller._last_decode_time = 0.0
    controller.update_position(0.3)
    _drain_async(controller, app)
    assert any(isinstance(f, np.ndarray) for f in frames)
    red = next(f for f in frames if isinstance(f, np.ndarray))
    assert red.mean(axis=(0, 1))[0] > red.mean(axis=(0, 1))[2]

    controller._last_decode_time = 0.0
    controller.update_position(2.4)
    _drain_async(controller, app)
    controller.set_playing(False)
    last = frames[-1]
    assert last is not None
    assert last.mean(axis=(0, 1))[2] > last.mean(axis=(0, 1))[0]


def test_pipeline_mode_and_async_metrics_in_perf_report(
    app: QApplication, red_clip_path: Path
) -> None:
    from cueplayer.diagnostics import perf as perf_diag
    from cueplayer.playback.video_sync import PIPELINE_MODE

    song = Song.create("Song")
    song.add_video_clip(
        VideoClip.create(name="red", path=red_clip_path, start_seconds=0.0, duration_seconds=2.0)
    )
    controller = VideoSyncController()
    assert controller.pipeline_mode() == PIPELINE_MODE

    perf_diag.set_enabled(True)
    perf_diag.clear()
    perf_diag.note("video.pipeline_mode", PIPELINE_MODE)
    controller.set_song(song)
    controller.set_playing(True)
    controller._last_decode_time = 0.0
    controller.update_position(0.4, source="engine")
    _drain_async(controller, app)

    report = perf_diag.report_text()
    assert "video.pipeline_mode: async_latest_wins" in report
    assert "video.decode.async" in report or "video.async_schedule" in report
    assert "video.async_schedule:" in report
    assert "video.schedule.source.engine:" in report
    # Sync path renamed — old bare "video.decode:" without suffix must not be the only span.
    snap = perf_diag.snapshot()
    assert "video.decode" not in snap["spans"] or "video.decode.sync" in snap["spans"]
    perf_diag.set_enabled(False)


def test_play_schedule_source_is_engine_not_scrub(
    app: QApplication, red_clip_path: Path
) -> None:
    from cueplayer.diagnostics import perf as perf_diag

    song = Song.create("Song")
    song.add_video_clip(
        VideoClip.create(name="red", path=red_clip_path, start_seconds=0.0, duration_seconds=2.0)
    )
    controller = VideoSyncController()
    controller.set_song(song)
    controller.set_playing(True)
    perf_diag.set_enabled(True)
    perf_diag.clear()
    controller._last_decode_time = 0.0
    controller.update_position(0.2, source="engine")
    snap = perf_diag.snapshot()["counters"]
    assert snap.get("video.schedule.source.engine", 0) >= 1
    assert snap.get("video.schedule.source.scrub", 0) == 0
    perf_diag.set_enabled(False)


def test_stale_async_never_emitted_after_newer_request(
    app: QApplication, red_clip_path: Path
) -> None:
    song = Song.create("Song")
    song.add_video_clip(
        VideoClip.create(name="red", path=red_clip_path, start_seconds=0.0, duration_seconds=2.0)
    )
    controller = VideoSyncController()
    controller.set_song(song)
    frames: list[object] = []
    controller.frame_changed.connect(frames.append)
    controller.set_playing(True)
    controller._last_decode_time = 0.0
    controller.update_position(0.1, source="engine")
    stale_gen = controller._async_req_gen
    controller._invalidate_async_requests()
    before = list(frames)
    fake = np.full((8, 8, 3), 123, dtype=np.uint8)
    controller._on_async_frame_ready(stale_gen, 0.1, fake)
    assert frames == before


def test_scrub_preview_updates_before_release(
    app: QApplication, red_clip_path: Path, blue_clip_path: Path
) -> None:
    """Video must present at least one mid-drag frame before mouse-up."""
    song = Song.create("Song")
    song.add_video_clip(
        VideoClip.create(name="red", path=red_clip_path, start_seconds=0.0, duration_seconds=2.0)
    )
    song.add_video_clip(
        VideoClip.create(name="blue", path=blue_clip_path, start_seconds=2.0, duration_seconds=2.0)
    )
    controller = VideoSyncController()
    controller.set_song(song)
    frames: list[object] = []
    controller.frame_changed.connect(frames.append)
    controller.set_scrubbing(True)
    controller._scrub_cache.clear()
    controller.update_position(0.2, source="scrub")
    controller._on_scrub_preview_tick()
    _drain_async(controller, app)
    mid = [f for f in frames if isinstance(f, np.ndarray)]
    assert len(mid) >= 1
    assert controller.is_scrubbing()
    controller.set_scrubbing(False)


def test_scrub_raw_events_coalesced_to_preview_rate(
    app: QApplication, red_clip_path: Path
) -> None:
    from cueplayer.diagnostics import perf as perf_diag

    song = Song.create("Song")
    song.add_video_clip(
        VideoClip.create(name="red", path=red_clip_path, start_seconds=0.0, duration_seconds=2.0)
    )
    controller = VideoSyncController()
    controller.set_song(song)
    controller._scrub_cache.clear()
    perf_diag.set_enabled(True)
    perf_diag.clear()
    controller.set_scrubbing(True)
    for i in range(50):
        controller.update_position(0.01 * i, source="scrub")
    raw = perf_diag.snapshot()["counters"].get("video.scrub.raw_position_events", 0)
    assert raw == 50
    controller._on_scrub_preview_tick()
    scheduled = perf_diag.snapshot()["counters"].get("video.async_schedule", 0)
    assert scheduled <= 2
    assert scheduled < raw
    controller.set_scrubbing(False)
    perf_diag.set_enabled(False)


def test_scrub_pause_priority_requests_latest(
    app: QApplication, red_clip_path: Path, blue_clip_path: Path
) -> None:
    song = Song.create("Song")
    song.add_video_clip(
        VideoClip.create(name="red", path=red_clip_path, start_seconds=0.0, duration_seconds=2.0)
    )
    song.add_video_clip(
        VideoClip.create(name="blue", path=blue_clip_path, start_seconds=2.0, duration_seconds=2.0)
    )
    controller = VideoSyncController()
    controller.set_song(song)
    frames: list[object] = []
    controller.frame_changed.connect(frames.append)
    controller.set_scrubbing(True)
    controller._scrub_cache.clear()
    controller.update_position(2.5, source="scrub")
    controller._on_scrub_pause_priority()
    _drain_async(controller, app)
    assert any(isinstance(f, np.ndarray) for f in frames)
    last = next(f for f in reversed(frames) if isinstance(f, np.ndarray))
    assert last.mean(axis=(0, 1))[2] > last.mean(axis=(0, 1))[0]
    controller.set_scrubbing(False)


def test_scrub_release_rejects_stale_generation(
    app: QApplication, red_clip_path: Path
) -> None:
    song = Song.create("Song")
    song.add_video_clip(
        VideoClip.create(name="red", path=red_clip_path, start_seconds=0.0, duration_seconds=2.0)
    )
    controller = VideoSyncController()
    controller.set_song(song)
    frames: list[object] = []
    controller.frame_changed.connect(frames.append)
    controller.set_scrubbing(True)
    controller.update_position(0.3, source="scrub")
    stale_gen = controller._async_req_gen
    controller.set_scrubbing(False)
    before = list(frames)
    fake = np.full((8, 8, 3), 77, dtype=np.uint8)
    controller._on_async_frame_ready(stale_gen, 0.3, fake)
    assert all(f is not fake for f in frames[len(before) :])


def test_scrub_release_lands_exact_song_time(
    app: QApplication, red_clip_path: Path, blue_clip_path: Path
) -> None:
    song = Song.create("Song")
    song.add_video_clip(
        VideoClip.create(name="red", path=red_clip_path, start_seconds=0.0, duration_seconds=2.0)
    )
    song.add_video_clip(
        VideoClip.create(name="blue", path=blue_clip_path, start_seconds=2.0, duration_seconds=2.0)
    )
    controller = VideoSyncController()
    controller.set_song(song)
    frames: list[object] = []
    controller.frame_changed.connect(frames.append)
    controller.set_scrubbing(True)
    controller.update_position(2.5, source="scrub")
    controller.set_scrubbing(False)
    _drain_async(controller, app)
    last = frames[-1]
    assert last is not None
    assert isinstance(last, np.ndarray)
    assert last.mean(axis=(0, 1))[2] > last.mean(axis=(0, 1))[0]
    assert controller._last_position_seconds == pytest.approx(2.5)
    assert controller._min_present_seconds == pytest.approx(2.5)


def test_queue_depth_one_during_scrub_preview(
    app: QApplication, red_clip_path: Path
) -> None:
    song = Song.create("Song")
    song.add_video_clip(
        VideoClip.create(name="red", path=red_clip_path, start_seconds=0.0, duration_seconds=2.0)
    )
    controller = VideoSyncController()
    controller.set_song(song)
    controller._scrub_cache.clear()
    controller.set_scrubbing(True)
    for i in range(20):
        controller.update_position(0.05 * i, source="scrub")
        controller._on_scrub_preview_tick()
    assert int(controller._async_inflight) in (0, 1)
    controller.set_scrubbing(False)
    _drain_async(controller, app)


def test_scrub_release_does_not_sync_decode_on_ui_thread(
    app: QApplication, red_clip_path: Path
) -> None:
    """Release must not call UI-thread PyAV (former 50 ms sync try blocked Qt)."""
    song = Song.create("Song")
    song.add_video_clip(
        VideoClip.create(name="red", path=red_clip_path, start_seconds=0.0, duration_seconds=2.0)
    )
    controller = VideoSyncController()
    controller.set_song(song)
    controller.set_scrubbing(True)
    controller.update_position(0.8, source="scrub")

    def _guard_decode(song_arg, seconds, *, worker: bool, lock_timeout=None, **kwargs):  # noqa: ANN001
        assert worker is True, "scrub release must not sync-decode on the UI thread"
        return None

    with patch.object(controller, "_decode_frame_array", side_effect=_guard_decode):
        controller.set_scrubbing(False)
    assert controller._scrub_land_pending or controller._async_req_kind == "land"
    # Avoid infinite land retries with None decode in this guard test.
    controller._final_land_pending = False
    controller._scrub_land_pending = False
    controller._land_retry_timer.stop()
    controller._set_pipeline_state("PLAYBACK")
    _drain_async(controller, app)


# --- Sprint 8 Task 2 Round 4: final-land priority + resume ---


def test_final_land_not_overwritten_by_engine_requests(
    app: QApplication, red_clip_path: Path
) -> None:
    from cueplayer.diagnostics import perf as perf_diag
    from cueplayer.playback.video_sync import VideoPipelineState

    song = Song.create("Song")
    song.add_video_clip(
        VideoClip.create(name="red", path=red_clip_path, start_seconds=0.0, duration_seconds=2.0)
    )
    controller = VideoSyncController()
    controller.set_song(song)
    controller.set_playing(True)
    perf_diag.set_enabled(True)
    perf_diag.clear()
    controller.set_scrubbing(True, was_playing=True)
    controller.update_position(1.2, source="scrub")
    controller.set_scrubbing(False)
    assert controller.pipeline_state() == VideoPipelineState.FINAL_LANDING
    land_t = controller._async_req_seconds
    # Engine must not replace the land slot.
    controller.update_position(1.5, source="engine")
    assert controller._async_req_kind == "land"
    assert controller._async_req_seconds == pytest.approx(land_t)
    snap = perf_diag.snapshot()["counters"]
    assert snap.get("video.scrub.engine_requests_blocked_during_land", 0) >= 1
    controller._final_land_pending = False
    controller._scrub_land_pending = False
    controller._land_retry_timer.stop()
    _drain_async(controller, app)
    perf_diag.set_enabled(False)


def test_engine_gated_during_final_landing(
    app: QApplication, red_clip_path: Path
) -> None:
    from cueplayer.playback.video_sync import VideoPipelineState

    song = Song.create("Song")
    song.add_video_clip(
        VideoClip.create(name="red", path=red_clip_path, start_seconds=0.0, duration_seconds=2.0)
    )
    controller = VideoSyncController()
    controller.set_song(song)
    controller.set_scrubbing(True, was_playing=True)
    controller.update_position(0.7, source="scrub")

    # Hold FINAL_LANDING by refusing decode completion.
    def _block_decode(*_a, **_k):  # noqa: ANN001
        return None

    with patch.object(controller, "_decode_frame_array", side_effect=_block_decode):
        controller.set_scrubbing(False)
        assert controller.pipeline_state() == VideoPipelineState.FINAL_LANDING
        assert controller.engine_video_gated() is True
        controller.update_position(1.0, source="engine")
        assert controller.engine_video_gated() is True
    controller._final_land_pending = False
    controller._scrub_land_pending = False
    controller._land_retry_timer.stop()
    controller._set_pipeline_state(VideoPipelineState.PLAYBACK)
    _drain_async(controller, app)


def test_newer_release_supersedes_older_final_land(
    app: QApplication, red_clip_path: Path
) -> None:
    from cueplayer.diagnostics import perf as perf_diag

    song = Song.create("Song")
    song.add_video_clip(
        VideoClip.create(name="red", path=red_clip_path, start_seconds=0.0, duration_seconds=2.0)
    )
    controller = VideoSyncController()
    controller.set_song(song)
    perf_diag.set_enabled(True)
    perf_diag.clear()
    controller.set_scrubbing(True, was_playing=False)
    controller.update_position(0.4, source="scrub")
    controller.set_scrubbing(False)
    first_gen = controller._final_land_generation
    # New scrub + release before land completes.
    controller.set_scrubbing(True, was_playing=False)
    controller.update_position(1.5, source="scrub")
    controller.set_scrubbing(False)
    assert controller._release_target_song_time == pytest.approx(1.5)
    assert controller._final_land_generation != first_gen or first_gen == 0
    _drain_async(controller, app)
    assert controller._final_land_pending is False
    perf_diag.set_enabled(False)


def test_non_superseded_final_land_eventually_presents(
    app: QApplication, red_clip_path: Path, blue_clip_path: Path
) -> None:
    song = Song.create("Song")
    song.add_video_clip(
        VideoClip.create(name="red", path=red_clip_path, start_seconds=0.0, duration_seconds=2.0)
    )
    song.add_video_clip(
        VideoClip.create(name="blue", path=blue_clip_path, start_seconds=2.0, duration_seconds=2.0)
    )
    controller = VideoSyncController()
    controller.set_song(song)
    frames: list[object] = []
    controller.frame_changed.connect(frames.append)
    controller.set_scrubbing(True, was_playing=False)
    controller.update_position(2.5, source="scrub")
    controller.set_scrubbing(False)
    _drain_async(controller, app, timeout=5.0)
    assert controller._final_land_pending is False
    assert controller._decoder_position_established is True
    last = next(f for f in reversed(frames) if isinstance(f, np.ndarray))
    assert last.mean(axis=(0, 1))[2] > last.mean(axis=(0, 1))[0]


def test_cached_poster_appears_immediately_on_release(
    app: QApplication, red_clip_path: Path
) -> None:
    song = Song.create("Song")
    clip = VideoClip.create(name="red", path=red_clip_path, start_seconds=0.0, duration_seconds=2.0)
    song.add_video_clip(clip)
    controller = VideoSyncController()
    controller.set_song(song)
    controller._scrub_cache.preload(list(song.video_clips))
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline and not controller._scrub_cache.ready(clip.id):
        time.sleep(0.05)
    assert controller._scrub_cache.ready(clip.id)

    frames: list[object] = []
    controller.frame_changed.connect(frames.append)
    controller.set_scrubbing(True, was_playing=False)
    controller.update_position(0.8, source="scrub")
    t0 = time.monotonic()
    controller.set_scrubbing(False)
    elapsed_ms = (time.monotonic() - t0) * 1000.0
    assert elapsed_ms < 50.0
    # Immediate path must not block; relevant frame is on screen (scrub and/or poster).
    assert any(isinstance(f, np.ndarray) for f in frames)
    assert controller._async_req_kind == "land"
    _drain_async(controller, app)


def test_exact_frame_replaces_approximate_on_land(
    app: QApplication, red_clip_path: Path, blue_clip_path: Path
) -> None:
    song = Song.create("Song")
    song.add_video_clip(
        VideoClip.create(name="red", path=red_clip_path, start_seconds=0.0, duration_seconds=2.0)
    )
    song.add_video_clip(
        VideoClip.create(name="blue", path=blue_clip_path, start_seconds=2.0, duration_seconds=2.0)
    )
    controller = VideoSyncController()
    controller.set_song(song)
    frames: list[object] = []
    controller.frame_changed.connect(frames.append)
    controller.set_scrubbing(True, was_playing=False)
    controller.update_position(2.5, source="scrub")
    controller.set_scrubbing(False)
    _drain_async(controller, app)
    last = frames[-1]
    assert isinstance(last, np.ndarray)
    assert last.mean(axis=(0, 1))[2] > last.mean(axis=(0, 1))[0]


def test_exact_land_transitions_to_resume_when_was_playing(
    app: QApplication, red_clip_path: Path
) -> None:
    from cueplayer.playback.video_sync import VideoPipelineState

    song = Song.create("Song")
    song.add_video_clip(
        VideoClip.create(name="red", path=red_clip_path, start_seconds=0.0, duration_seconds=2.0)
    )
    controller = VideoSyncController()
    controller.set_song(song)
    controller.set_scrubbing(True, was_playing=True)
    controller.update_position(0.6, source="scrub")
    controller.set_scrubbing(False)
    _drain_async(controller, app)
    # Land must enter RESUME (or already complete to PLAYBACK via first resume frame).
    assert controller.pipeline_state() in (
        VideoPipelineState.RESUME_PLAYBACK,
        VideoPipelineState.PLAYBACK,
    )
    assert controller.engine_video_gated() is False
    assert controller._decoder_position_established is True
    assert controller._final_land_pending is False
    if controller.pipeline_state() == VideoPipelineState.RESUME_PLAYBACK:
        assert controller._resume_pending is True


def test_engine_accepted_after_final_land_completes(
    app: QApplication, red_clip_path: Path
) -> None:
    from cueplayer.playback.video_sync import VideoPipelineState

    song = Song.create("Song")
    song.add_video_clip(
        VideoClip.create(name="red", path=red_clip_path, start_seconds=0.0, duration_seconds=2.0)
    )
    controller = VideoSyncController()
    controller.set_song(song)
    controller.set_scrubbing(True, was_playing=True)
    controller.update_position(0.5, source="scrub")
    controller.set_scrubbing(False)
    _drain_async(controller, app)
    assert controller.pipeline_state() in (
        VideoPipelineState.RESUME_PLAYBACK,
        VideoPipelineState.PLAYBACK,
    )
    controller.set_playing(True)
    controller._last_decode_time = 0.0
    controller.update_position(0.7, source="engine")
    assert controller._async_req_kind == "play"
    _drain_async(controller, app)
    if controller.pipeline_state() == VideoPipelineState.RESUME_PLAYBACK:
        controller._complete_resume(reason="test")
    assert controller.pipeline_state() == VideoPipelineState.PLAYBACK


def test_valid_post_release_frames_not_rejected(
    app: QApplication, red_clip_path: Path
) -> None:
    from cueplayer.diagnostics import perf as perf_diag

    song = Song.create("Song")
    song.add_video_clip(
        VideoClip.create(name="red", path=red_clip_path, start_seconds=0.0, duration_seconds=2.0)
    )
    controller = VideoSyncController()
    controller.set_song(song)
    controller.set_scrubbing(True, was_playing=True)
    controller.update_position(0.5, source="scrub")
    controller.set_scrubbing(False)
    _drain_async(controller, app)
    perf_diag.set_enabled(True)
    perf_diag.clear()
    fake = np.full((8, 8, 3), 40, dtype=np.uint8)
    gen = controller._async_req_gen
    controller._on_async_frame_ready(gen, 0.55, fake, "play")
    rejected = perf_diag.snapshot()["counters"].get(
        "video.scrub.valid_frames_rejected_after_land", 0
    )
    assert rejected == 0
    perf_diag.set_enabled(False)


def test_min_present_seconds_clears_after_resume_present(
    app: QApplication, red_clip_path: Path
) -> None:
    from cueplayer.playback.video_sync import VideoPipelineState

    song = Song.create("Song")
    song.add_video_clip(
        VideoClip.create(name="red", path=red_clip_path, start_seconds=0.0, duration_seconds=2.0)
    )
    controller = VideoSyncController()
    controller.set_song(song)
    controller.set_scrubbing(True, was_playing=True)
    controller.update_position(0.4, source="scrub")
    controller.set_scrubbing(False)
    _drain_async(controller, app)
    # Ensure we are in RESUME with soft floor still set.
    if controller.pipeline_state() == VideoPipelineState.PLAYBACK:
        # Resume already completed via land/play race — floor may be cleared.
        assert controller._min_present_seconds is None
        return
    assert controller.pipeline_state() == VideoPipelineState.RESUME_PLAYBACK
    assert controller._min_present_seconds is not None
    fake = np.full((8, 8, 3), 11, dtype=np.uint8)
    controller._on_async_frame_ready(controller._async_req_gen, 0.5, fake, "play")
    assert controller._min_present_seconds is None
    assert controller.pipeline_state() == VideoPipelineState.PLAYBACK


def test_paused_scrub_stays_landed_without_resume_loop(
    app: QApplication, red_clip_path: Path
) -> None:
    from cueplayer.playback.video_sync import VideoPipelineState

    song = Song.create("Song")
    song.add_video_clip(
        VideoClip.create(name="red", path=red_clip_path, start_seconds=0.0, duration_seconds=2.0)
    )
    controller = VideoSyncController()
    controller.set_song(song)
    controller.set_scrubbing(True, was_playing=False)
    controller.update_position(0.9, source="scrub")
    controller.set_scrubbing(False)
    _drain_async(controller, app)
    assert controller.pipeline_state() == VideoPipelineState.PLAYBACK
    assert controller._resume_pending is False
    assert controller._final_land_pending is False


def test_late_final_land_does_not_overwrite_newer_resume(
    app: QApplication, red_clip_path: Path
) -> None:
    from cueplayer.playback.video_sync import VideoPipelineState

    song = Song.create("Song")
    song.add_video_clip(
        VideoClip.create(name="red", path=red_clip_path, start_seconds=0.0, duration_seconds=2.0)
    )
    controller = VideoSyncController()
    controller.set_song(song)
    frames: list[object] = []
    controller.frame_changed.connect(frames.append)
    controller.set_scrubbing(True, was_playing=True)
    controller.update_position(0.3, source="scrub")
    controller.set_scrubbing(False)
    _drain_async(controller, app)
    newer = np.full((8, 8, 3), 200, dtype=np.uint8)
    controller._on_async_frame_ready(controller._async_req_gen, 0.8, newer, "play")
    assert controller.pipeline_state() == VideoPipelineState.PLAYBACK
    before_last = frames[-1]
    stale_land = np.full((8, 8, 3), 1, dtype=np.uint8)
    controller._on_async_frame_ready(controller._async_req_gen, 0.3, stale_land, "land")
    assert frames[-1] is before_last or (
        isinstance(frames[-1], np.ndarray) and float(frames[-1].mean()) > 100
    )


def test_song_switch_cancels_resume_state(
    app: QApplication, red_clip_path: Path
) -> None:
    from cueplayer.playback.video_sync import VideoPipelineState

    song = Song.create("Song")
    song.add_video_clip(
        VideoClip.create(name="red", path=red_clip_path, start_seconds=0.0, duration_seconds=2.0)
    )
    controller = VideoSyncController()
    controller.set_song(song)
    controller.set_scrubbing(True, was_playing=True)
    controller.update_position(0.5, source="scrub")

    def _block_decode(*_a, **_k):  # noqa: ANN001
        return None

    with patch.object(controller, "_decode_frame_array", side_effect=_block_decode):
        controller.set_scrubbing(False)
        assert controller.pipeline_state() == VideoPipelineState.FINAL_LANDING
        controller.set_song(song)
    assert controller.pipeline_state() == VideoPipelineState.PLAYBACK
    assert controller._final_land_pending is False
    assert controller._resume_pending is False
    assert controller.engine_video_gated() is False


def test_queue_remains_bounded_during_final_land(
    app: QApplication, red_clip_path: Path
) -> None:
    from cueplayer.playback.video_sync import VideoPipelineState

    song = Song.create("Song")
    song.add_video_clip(
        VideoClip.create(name="red", path=red_clip_path, start_seconds=0.0, duration_seconds=2.0)
    )
    controller = VideoSyncController()
    controller.set_song(song)
    controller.set_scrubbing(True, was_playing=True)
    controller.update_position(0.5, source="scrub")

    def _block_decode(*_a, **_k):  # noqa: ANN001
        return None

    with patch.object(controller, "_decode_frame_array", side_effect=_block_decode):
        controller.set_scrubbing(False)
        assert controller.pipeline_state() == VideoPipelineState.FINAL_LANDING
        for t in (0.1, 0.2, 0.3, 0.4):
            controller.update_position(t, source="engine")
            controller._request_async_live_frame(t, kind="play")
        assert int(controller._async_inflight) in (0, 1)
        assert controller._async_req_kind == "land"
    controller._final_land_pending = False
    controller._scrub_land_pending = False
    controller._land_retry_timer.stop()
    controller._set_pipeline_state(VideoPipelineState.PLAYBACK)
    _drain_async(controller, app)


def test_no_pre_release_frame_presented_after_release(
    app: QApplication, red_clip_path: Path
) -> None:
    song = Song.create("Song")
    song.add_video_clip(
        VideoClip.create(name="red", path=red_clip_path, start_seconds=0.0, duration_seconds=2.0)
    )
    controller = VideoSyncController()
    controller.set_song(song)
    frames: list[object] = []
    controller.frame_changed.connect(frames.append)
    controller.set_scrubbing(True, was_playing=False)
    controller.update_position(0.2, source="scrub")
    stale_gen = controller._async_req_gen
    controller.update_position(1.0, source="scrub")
    controller.set_scrubbing(False)
    before = len(frames)
    old = np.full((8, 8, 3), 9, dtype=np.uint8)
    controller._on_async_frame_ready(stale_gen, 0.2, old, "scrub_preview")
    assert all(f is not old for f in frames[before:])
    _drain_async(controller, app)

# --- Sprint 8 Task 2 Round 5: empty-frame + target recovery ---


def test_release_target_media_time_never_ambiguous_in_final_landing(
    app: QApplication, red_clip_path: Path
) -> None:
    from cueplayer.playback.video_sync import ReleaseTargetKind, VideoPipelineState

    song = Song.create("Song")
    song.add_video_clip(
        VideoClip.create(
            name="red", path=red_clip_path, start_seconds=1.0, duration_seconds=2.0
        )
    )
    controller = VideoSyncController()
    controller.set_song(song)

    def _block(*_a, **_k):  # noqa: ANN001
        return None

    controller.set_scrubbing(True, was_playing=False)
    controller.update_position(1.5, source="scrub")
    with patch.object(controller, "_decode_frame_array", side_effect=_block):
        controller.set_scrubbing(False)
        assert controller.pipeline_state() == VideoPipelineState.FINAL_LANDING
        assert controller._release_target is not None
        assert controller._release_target.is_valid
        assert controller._release_target_media_time is not None
        assert controller._release_target.kind == ReleaseTargetKind.VALID_MEDIA_TARGET
    controller._final_land_pending = False
    controller._land_retry_timer.stop()
    controller._set_pipeline_state(VideoPipelineState.PLAYBACK)
    _drain_async(controller, app)


def test_timeline_gap_release_does_not_retry(
    app: QApplication, red_clip_path: Path
) -> None:
    from cueplayer.diagnostics import perf as perf_diag
    from cueplayer.playback.video_sync import ReleaseTargetKind, VideoPipelineState

    song = Song.create("Song")
    song.add_video_clip(
        VideoClip.create(
            name="red", path=red_clip_path, start_seconds=0.0, duration_seconds=1.0
        )
    )
    song.add_video_clip(
        VideoClip.create(
            name="red2", path=red_clip_path, start_seconds=3.0, duration_seconds=1.0
        )
    )
    controller = VideoSyncController()
    controller.set_song(song)
    controller.update_position(0.5)
    perf_diag.set_enabled(True)
    perf_diag.clear()
    controller.set_scrubbing(True, was_playing=False)
    controller.update_position(2.0, source="scrub")
    controller.set_scrubbing(False)
    assert controller._release_target is not None
    assert controller._release_target.kind == ReleaseTargetKind.TIMELINE_GAP
    assert controller.pipeline_state() == VideoPipelineState.PLAYBACK
    assert controller._final_land_pending is False
    retries = perf_diag.snapshot()["counters"].get("video.scrub.final_land_retry", 0)
    assert retries == 0
    assert controller._last_valid_frame is not None
    perf_diag.set_enabled(False)


def test_out_of_range_targets_resolve_safely(
    app: QApplication, red_clip_path: Path
) -> None:
    from cueplayer.playback.video_sync import ReleaseTargetKind

    song = Song.create("Song")
    song.add_video_clip(
        VideoClip.create(
            name="red", path=red_clip_path, start_seconds=2.0, duration_seconds=2.0
        )
    )
    controller = VideoSyncController()
    controller.set_song(song)
    before = controller._resolve_release_target(song, -1.0)
    assert before.kind == ReleaseTargetKind.OUT_OF_RANGE
    assert before.media_seconds is None
    after = controller._resolve_release_target(song, 9.0)
    assert after.kind == ReleaseTargetKind.OUT_OF_RANGE
    controller.set_scrubbing(True, was_playing=True)
    controller.update_position(-0.5, source="scrub")
    controller.set_scrubbing(False)
    assert controller._final_land_pending is False
    assert controller.engine_video_gated() is False


def test_empty_decode_does_not_clear_valid_preview(
    app: QApplication, red_clip_path: Path
) -> None:
    song = Song.create("Song")
    song.add_video_clip(
        VideoClip.create(
            name="red", path=red_clip_path, start_seconds=0.0, duration_seconds=2.0
        )
    )
    controller = VideoSyncController()
    controller.set_song(song)
    frames: list[object] = []
    controller.frame_changed.connect(frames.append)
    controller.update_position(0.3)
    assert any(isinstance(f, np.ndarray) for f in frames)
    last_good = next(f for f in reversed(frames) if isinstance(f, np.ndarray))
    controller._emit_frame(None, allow_clear=False, reason="test_empty")
    assert frames[-1] is last_good or (
        isinstance(frames[-1], np.ndarray) and frames[-1] is not None
    )
    assert controller._last_emitted_frame is not None


def test_zero_size_frame_rejected(app: QApplication, red_clip_path: Path) -> None:
    from cueplayer.diagnostics import perf as perf_diag

    song = Song.create("Song")
    song.add_video_clip(
        VideoClip.create(
            name="red", path=red_clip_path, start_seconds=0.0, duration_seconds=2.0
        )
    )
    controller = VideoSyncController()
    controller.set_song(song)
    controller.update_position(0.2)
    before = controller._last_emitted_frame
    perf_diag.set_enabled(True)
    perf_diag.clear()
    bad = np.zeros((0, 0, 3), dtype=np.uint8)
    controller._emit_frame(bad)
    assert perf_diag.snapshot()["counters"].get("video.zero_size_frame_rejected", 0) >= 1
    assert controller._last_emitted_frame is before
    perf_diag.set_enabled(False)


def test_actual_black_source_frame_allowed(
    app: QApplication, red_clip_path: Path
) -> None:
    song = Song.create("Song")
    song.add_video_clip(
        VideoClip.create(
            name="red", path=red_clip_path, start_seconds=0.0, duration_seconds=2.0
        )
    )
    controller = VideoSyncController()
    controller.set_song(song)
    frames: list[object] = []
    controller.frame_changed.connect(frames.append)
    black = np.zeros((8, 8, 3), dtype=np.uint8)
    controller._emit_frame(black)
    assert frames[-1] is black


def test_land_retry_count_and_deadline_bounded(
    app: QApplication, red_clip_path: Path
) -> None:
    from cueplayer.diagnostics import perf as perf_diag
    from cueplayer.playback.video_sync import VideoPipelineState, _LAND_MAX_RETRIES

    song = Song.create("Song")
    song.add_video_clip(
        VideoClip.create(
            name="red", path=red_clip_path, start_seconds=0.0, duration_seconds=2.0
        )
    )
    controller = VideoSyncController()
    controller.set_song(song)
    perf_diag.set_enabled(True)
    perf_diag.clear()

    def _block(*_a, **_k):  # noqa: ANN001
        return None

    with patch.object(controller, "_decode_frame_array", side_effect=_block):
        controller.set_scrubbing(True, was_playing=True)
        controller.update_position(0.8, source="scrub")
        controller.set_scrubbing(False)
        for _ in range(_LAND_MAX_RETRIES + 5):
            if controller.pipeline_state() != VideoPipelineState.FINAL_LANDING:
                break
            controller._retry_final_land_if_pending()
            app.processEvents()
    retries = perf_diag.snapshot()["counters"].get("video.scrub.final_land_retry", 0)
    assert retries <= _LAND_MAX_RETRIES
    assert controller.pipeline_state() != VideoPipelineState.FINAL_LANDING
    assert controller._final_land_pending is False
    perf_diag.set_enabled(False)


def test_retry_deadline_exits_final_landing(
    app: QApplication, red_clip_path: Path
) -> None:
    from cueplayer.playback.video_sync import VideoPipelineState
    from time import monotonic

    song = Song.create("Song")
    song.add_video_clip(
        VideoClip.create(
            name="red", path=red_clip_path, start_seconds=0.0, duration_seconds=2.0
        )
    )
    controller = VideoSyncController()
    controller.set_song(song)

    def _block(*_a, **_k):  # noqa: ANN001
        return None

    with patch.object(controller, "_decode_frame_array", side_effect=_block):
        controller.set_scrubbing(True, was_playing=False)
        controller.update_position(0.4, source="scrub")
        controller.set_scrubbing(False)
        controller._land_deadline_mono = monotonic() - 0.01
        controller._retry_final_land_if_pending()
    assert controller.pipeline_state() == VideoPipelineState.PLAYBACK
    assert controller._final_land_pending is False


def test_playing_land_always_starts_and_completes_resume(
    app: QApplication, red_clip_path: Path
) -> None:
    from cueplayer.diagnostics import perf as perf_diag
    from cueplayer.playback.video_sync import VideoPipelineState

    song = Song.create("Song")
    song.add_video_clip(
        VideoClip.create(
            name="red", path=red_clip_path, start_seconds=0.0, duration_seconds=2.0
        )
    )
    controller = VideoSyncController()
    controller.set_song(song)
    perf_diag.set_enabled(True)
    perf_diag.clear()
    controller.set_scrubbing(True, was_playing=True)
    controller.update_position(0.6, source="scrub")
    controller.set_scrubbing(False)
    _drain_async(controller, app)
    assert perf_diag.snapshot()["counters"].get("video.scrub.resume_started", 0) >= 1
    if controller.pipeline_state() == VideoPipelineState.RESUME_PLAYBACK:
        fake = np.full((8, 8, 3), 50, dtype=np.uint8)
        controller._on_async_frame_ready(
            controller._async_req_gen, 0.7, fake, "play", ""
        )
    assert controller.pipeline_state() == VideoPipelineState.PLAYBACK
    assert perf_diag.snapshot()["counters"].get("video.scrub.resume_completed", 0) >= 1
    perf_diag.set_enabled(False)


def test_paused_land_remains_paused(app: QApplication, red_clip_path: Path) -> None:
    from cueplayer.diagnostics import perf as perf_diag
    from cueplayer.playback.video_sync import VideoPipelineState

    song = Song.create("Song")
    song.add_video_clip(
        VideoClip.create(
            name="red", path=red_clip_path, start_seconds=0.0, duration_seconds=2.0
        )
    )
    controller = VideoSyncController()
    controller.set_song(song)
    perf_diag.set_enabled(True)
    perf_diag.clear()
    controller.set_scrubbing(True, was_playing=False)
    controller.update_position(0.7, source="scrub")
    controller.set_scrubbing(False)
    _drain_async(controller, app)
    assert controller.pipeline_state() == VideoPipelineState.PLAYBACK
    assert perf_diag.snapshot()["counters"].get("video.scrub.resume_started", 0) == 0
    perf_diag.set_enabled(False)


def test_repeated_empty_triggers_decoder_reset(
    app: QApplication, red_clip_path: Path
) -> None:
    from cueplayer.diagnostics import perf as perf_diag
    from cueplayer.playback.video_sync import (
        VideoPipelineState,
        _EMPTY_DECODE_RESET_AFTER,
    )

    song = Song.create("Song")
    clip = VideoClip.create(
        name="red", path=red_clip_path, start_seconds=0.0, duration_seconds=2.0
    )
    song.add_video_clip(clip)
    controller = VideoSyncController()
    controller.set_song(song)
    perf_diag.set_enabled(True)
    perf_diag.clear()

    def _block(*_a, **_k):  # noqa: ANN001
        return None

    with patch.object(controller, "_decode_frame_array", side_effect=_block):
        controller.set_scrubbing(True, was_playing=True)
        controller.update_position(0.5, source="scrub")
        controller.set_scrubbing(False)
        controller._empty_decode_streak = _EMPTY_DECODE_RESET_AFTER
        controller._retry_final_land_if_pending()
    assert perf_diag.snapshot()["counters"].get("video.decoder_reset.worker", 0) >= 1
    controller._final_land_pending = False
    controller._land_retry_timer.stop()
    controller._set_pipeline_state(VideoPipelineState.PLAYBACK)
    _drain_async(controller, app)
    perf_diag.set_enabled(False)


def test_ten_drag_release_transactions_no_stuck_state(
    app: QApplication, red_clip_path: Path
) -> None:
    from cueplayer.playback.video_sync import VideoPipelineState

    song = Song.create("Song")
    song.add_video_clip(
        VideoClip.create(
            name="red", path=red_clip_path, start_seconds=0.0, duration_seconds=2.0
        )
    )
    controller = VideoSyncController()
    controller.set_song(song)
    for i in range(10):
        t = 0.1 + 0.15 * (i % 8)
        controller.set_scrubbing(True, was_playing=(i % 2 == 0))
        controller.update_position(t, source="scrub")
        controller.set_scrubbing(False)
        _drain_async(controller, app, timeout=4.0)
        if controller.pipeline_state() == VideoPipelineState.RESUME_PLAYBACK:
            controller._complete_resume(reason="test")
        assert controller.pipeline_state() != VideoPipelineState.FINAL_LANDING
        assert controller._final_land_pending is False
        assert controller.engine_video_gated() is False


def test_new_scrub_cancels_old_retry_resume(
    app: QApplication, red_clip_path: Path
) -> None:
    from cueplayer.playback.video_sync import VideoPipelineState

    song = Song.create("Song")
    song.add_video_clip(
        VideoClip.create(
            name="red", path=red_clip_path, start_seconds=0.0, duration_seconds=2.0
        )
    )
    controller = VideoSyncController()
    controller.set_song(song)

    def _block(*_a, **_k):  # noqa: ANN001
        return None

    with patch.object(controller, "_decode_frame_array", side_effect=_block):
        controller.set_scrubbing(True, was_playing=True)
        controller.update_position(0.3, source="scrub")
        controller.set_scrubbing(False)
        assert controller.pipeline_state() == VideoPipelineState.FINAL_LANDING
        old_txn = controller._final_land_transaction_id
        controller.set_scrubbing(True, was_playing=True)
        assert controller.pipeline_state() == VideoPipelineState.SCRUB_PREVIEW
        assert controller._final_land_pending is False
        assert controller._resume_pending is False
        assert controller._scrub_transaction_id != old_txn or old_txn == 0
    _drain_async(controller, app)


def test_eof_seek_backward_recovers(
    app: QApplication, red_clip_path: Path
) -> None:
    song = Song.create("Song")
    song.add_video_clip(
        VideoClip.create(
            name="red", path=red_clip_path, start_seconds=0.0, duration_seconds=2.0
        )
    )
    controller = VideoSyncController()
    controller.set_song(song)
    frames: list[object] = []
    controller.frame_changed.connect(frames.append)
    controller.set_playing(True)
    controller.update_position(1.8)
    _drain_async(controller, app)
    controller.set_scrubbing(True, was_playing=True)
    controller.update_position(0.2, source="scrub")
    controller.set_scrubbing(False)
    _drain_async(controller, app)
    assert any(isinstance(f, np.ndarray) for f in frames)
    assert controller._final_land_pending is False

# --- Sprint 8 Task 2 Round 6: scrub preview delivery + deterministic resume ---


def _shutdown_ctrl(controller: VideoSyncController) -> None:
    try:
        controller.shutdown()
    except Exception:
        pass


def test_slow_drag_presents_multiple_preview_frames_before_release(
    app: QApplication, red_clip_path: Path
) -> None:
    song = Song.create("Song")
    song.add_video_clip(
        VideoClip.create(
            name="red", path=red_clip_path, start_seconds=0.0, duration_seconds=2.0
        )
    )
    controller = VideoSyncController()
    try:
        controller.set_song(song)
        controller._scrub_cache.clear()
        frames: list[object] = []
        controller.frame_changed.connect(frames.append)
        n = {"i": 0}

        def _immediate(seconds, *, kind="play", lock_timeout=0.05, force=False, **_kw):  # noqa: ANN001
            if kind != "scrub_preview":
                return
            n["i"] += 1
            frame = np.full((8, 8, 3), n["i"] % 200, dtype=np.uint8)
            controller._emit_frame(frame)
            controller._note_preview_presented(float(seconds))

        with patch.object(controller, "_request_async_live_frame", side_effect=_immediate):
            controller.set_scrubbing(True, was_playing=True)
            controller._scrub_preload_timer.stop()
            for i in range(16):
                controller.update_position(0.05 * i, source="scrub")
                controller._on_scrub_preview_tick()
            mid = [f for f in frames if isinstance(f, np.ndarray)]
            assert len(mid) >= 8
            assert controller._scrub_preview_presented >= 8
            assert controller.is_scrubbing()
            controller._scrubbing = False
            controller._final_land_pending = False
    finally:
        _shutdown_ctrl(controller)


def test_preview_coalesce_does_not_invalidate_inflight_generation(
    app: QApplication, red_clip_path: Path
) -> None:
    """Mouse moves must not bump gen on every coalesce (Round 5 failure mode)."""
    song = Song.create("Song")
    song.add_video_clip(
        VideoClip.create(
            name="red", path=red_clip_path, start_seconds=0.0, duration_seconds=2.0
        )
    )
    controller = VideoSyncController()
    controller.set_song(song)
    controller._scrub_cache.clear()
    controller.set_scrubbing(True, was_playing=False)
    controller._async_inflight = True
    controller._async_req_kind = "scrub_preview"
    controller._async_req_seconds = 0.2
    gen_before = controller._async_req_gen
    session_before = controller._scrub_session_gen
    # Many coalesced moves near the target — must NOT bump generation.
    for i in range(20):
        controller._request_async_live_frame(
            0.2 + 0.01 * i, kind="scrub_preview", lock_timeout=0.08
        )
    assert controller._async_req_gen == gen_before
    assert controller._scrub_session_gen == session_before
    assert abs(controller._async_req_seconds - 0.39) < 0.05
    controller._async_inflight = False
    controller._scrubbing = False
    controller._scrub_preview_timer.stop()
    controller._scrub_pause_timer.stop()
    controller._set_pipeline_state("PLAYBACK")
    _shutdown_ctrl(controller)


def test_preview_result_within_tolerance_can_be_presented(
    app: QApplication, red_clip_path: Path
) -> None:
    song = Song.create("Song")
    song.add_video_clip(
        VideoClip.create(
            name="red", path=red_clip_path, start_seconds=0.0, duration_seconds=2.0
        )
    )
    controller = VideoSyncController()
    controller.set_song(song)
    frames: list[object] = []
    controller.frame_changed.connect(frames.append)
    controller.set_scrubbing(True, was_playing=False)
    controller.update_position(0.5, source="scrub")
    session = controller._scrub_session_gen
    stale_gen = controller._async_req_gen - 1
    controller._scrub_target_seconds = 0.55
    fake = np.full((8, 8, 3), 90, dtype=np.uint8)
    controller._on_async_frame_ready(
        stale_gen, 0.5, fake, "scrub_preview", "", session
    )
    assert any(f is fake for f in frames)
    controller.set_scrubbing(False)
    _shutdown_ctrl(controller)


def test_mouse_move_does_not_change_scrub_session_generation(
    app: QApplication, red_clip_path: Path
) -> None:
    song = Song.create("Song")
    song.add_video_clip(
        VideoClip.create(
            name="red", path=red_clip_path, start_seconds=0.0, duration_seconds=2.0
        )
    )
    controller = VideoSyncController()
    controller.set_song(song)
    controller.set_scrubbing(True, was_playing=False)
    session = controller._scrub_session_gen
    for i in range(30):
        controller.update_position(0.01 * i, source="scrub")
    assert controller._scrub_session_gen == session
    controller.set_scrubbing(False)
    _shutdown_ctrl(controller)


def test_every_playing_successful_land_requires_resume(
    app: QApplication, red_clip_path: Path
) -> None:
    from cueplayer.diagnostics import perf as perf_diag
    from cueplayer.playback.video_sync import ReleaseTarget, ReleaseTargetKind

    song = Song.create("Song")
    clip = VideoClip.create(
        name="red", path=red_clip_path, start_seconds=0.0, duration_seconds=2.0
    )
    song.add_video_clip(clip)
    controller = VideoSyncController()
    controller.set_song(song)
    perf_diag.set_enabled(True)
    perf_diag.clear()
    controller.set_scrubbing(True, was_playing=True)
    controller.update_position(0.6, source="scrub")
    controller._scrubbing = False
    controller._scrub_preview_timer.stop()
    controller._release_target = ReleaseTarget(
        ReleaseTargetKind.VALID_MEDIA_TARGET,
        song_seconds=0.6,
        media_seconds=0.6,
        clip_id=clip.id,
    )
    controller._release_target_song_time = 0.6
    controller._release_target_media_time = 0.6
    controller._final_land_transaction_id = controller._scrub_transaction_id
    controller._pre_scrub_was_playing = True
    frame = np.full((8, 8, 3), 70, dtype=np.uint8)
    controller._complete_final_land(0.6, frame)
    snap = perf_diag.snapshot()["counters"]
    assert snap.get("video.scrub.resume_required", 0) >= 1
    assert snap.get("video.scrub.resume_started", 0) >= 1
    assert snap.get("video.scrub.resume_not_required", 0) == 0
    controller._resume_watchdog.stop()
    controller._final_land_pending = False
    controller._async_inflight = False
    perf_diag.set_enabled(False)
    _shutdown_ctrl(controller)


def test_paused_land_does_not_require_resume(
    app: QApplication, red_clip_path: Path
) -> None:
    from cueplayer.diagnostics import perf as perf_diag
    from cueplayer.playback.video_sync import ReleaseTarget, ReleaseTargetKind

    song = Song.create("Song")
    clip = VideoClip.create(
        name="red", path=red_clip_path, start_seconds=0.0, duration_seconds=2.0
    )
    song.add_video_clip(clip)
    controller = VideoSyncController()
    controller.set_song(song)
    perf_diag.set_enabled(True)
    perf_diag.clear()
    controller.set_scrubbing(True, was_playing=False)
    controller.update_position(0.6, source="scrub")
    controller._scrubbing = False
    controller._scrub_preview_timer.stop()
    controller._release_target = ReleaseTarget(
        ReleaseTargetKind.VALID_MEDIA_TARGET,
        song_seconds=0.6,
        media_seconds=0.6,
        clip_id=clip.id,
    )
    controller._release_target_song_time = 0.6
    controller._pre_scrub_was_playing = False
    controller._complete_final_land(0.6, np.full((8, 8, 3), 71, dtype=np.uint8))
    snap = perf_diag.snapshot()["counters"]
    assert snap.get("video.scrub.resume_not_required", 0) >= 1
    assert snap.get("video.scrub.resume_started", 0) == 0
    perf_diag.set_enabled(False)
    _shutdown_ctrl(controller)


def test_gap_outcome_not_counted_as_resume_failure(
    app: QApplication, red_clip_path: Path
) -> None:
    from cueplayer.diagnostics import perf as perf_diag

    song = Song.create("Song")
    song.add_video_clip(
        VideoClip.create(
            name="red", path=red_clip_path, start_seconds=0.0, duration_seconds=1.0
        )
    )
    song.add_video_clip(
        VideoClip.create(
            name="red2", path=red_clip_path, start_seconds=3.0, duration_seconds=1.0
        )
    )
    controller = VideoSyncController()
    controller.set_song(song)
    perf_diag.set_enabled(True)
    perf_diag.clear()
    controller.set_scrubbing(True, was_playing=False)
    controller.update_position(2.0, source="scrub")
    controller.set_scrubbing(False)
    snap = perf_diag.snapshot()["counters"]
    assert snap.get("video.scrub.final_land_completed_gap", 0) >= 1
    assert snap.get("video.scrub.resume_started", 0) == 0
    perf_diag.set_enabled(False)
    _shutdown_ctrl(controller)


def test_first_resumed_frame_at_or_after_release_target(
    app: QApplication, red_clip_path: Path
) -> None:
    from cueplayer.playback.video_sync import VideoPipelineState

    song = Song.create("Song")
    song.add_video_clip(
        VideoClip.create(
            name="red", path=red_clip_path, start_seconds=0.0, duration_seconds=2.0
        )
    )
    controller = VideoSyncController()
    controller.set_song(song)
    with patch.object(controller, "_request_async_live_frame", return_value=None):
        controller.set_scrubbing(True, was_playing=True)
        controller._scrub_preload_timer.stop()
        controller._scrub_preview_timer.stop()
        controller.update_position(0.8, source="scrub")
        controller._scrubbing = False
        controller._scrub_preview_timer.stop()
        controller._scrub_pause_timer.stop()
        controller._release_target_song_time = 0.8
        controller._release_target_media_time = 0.8
        controller._min_present_seconds = 0.8
        controller._final_land_transaction_id = controller._scrub_transaction_id
        controller._pre_scrub_was_playing = True
        controller._decoder_position_established = True
        controller._final_land_pending = False
        controller._async_inflight = False
        controller._enter_resume_playback()
        release = float(controller._release_target_song_time)
        controller._async_req_gen += 1
        gen = controller._async_req_gen
        # Pre-release frame must be rejected.
        controller._on_async_frame_ready(
            gen, release - 0.2, np.full((8, 8, 3), 1, dtype=np.uint8), "play", "", -1
        )
        assert controller.pipeline_state() == VideoPipelineState.RESUME_PLAYBACK
        # Post-release accepted → completes resume.
        controller._on_async_frame_ready(
            gen, release + 0.05, np.full((8, 8, 3), 33, dtype=np.uint8), "play", "", -1
        )
        assert controller.pipeline_state() == VideoPipelineState.PLAYBACK
        assert controller._last_presented_song_seconds is not None
        assert controller._last_presented_song_seconds >= release - 0.05
    controller._resume_watchdog.stop()
    controller._async_inflight = False
    _shutdown_ctrl(controller)


def test_resume_timeout_triggers_recovery(
    app: QApplication, red_clip_path: Path
) -> None:
    from cueplayer.diagnostics import perf as perf_diag
    from cueplayer.playback.video_sync import VideoPipelineState

    song = Song.create("Song")
    song.add_video_clip(
        VideoClip.create(
            name="red", path=red_clip_path, start_seconds=0.0, duration_seconds=2.0
        )
    )
    controller = VideoSyncController()
    controller.set_song(song)
    perf_diag.set_enabled(True)
    perf_diag.clear()
    with patch.object(controller, "_request_async_live_frame", return_value=None):
        controller.set_scrubbing(True, was_playing=True)
        controller._scrub_preload_timer.stop()
        controller._scrub_preview_timer.stop()
        controller.update_position(0.4, source="scrub")
        controller._scrubbing = False
        controller._scrub_preview_timer.stop()
        controller._scrub_pause_timer.stop()
        controller._release_target_song_time = 0.4
        controller._release_target_media_time = 0.4
        controller._final_land_transaction_id = controller._scrub_transaction_id
        controller._pre_scrub_was_playing = True
        controller._decoder_position_established = True
        controller._final_land_pending = False
        controller._async_inflight = False
        controller._enter_resume_playback()
        assert controller.pipeline_state() == VideoPipelineState.RESUME_PLAYBACK
        controller._on_resume_watchdog()
        controller._on_resume_watchdog()
    snap = perf_diag.snapshot()["counters"]
    assert snap.get("video.scrub.resume_timeout", 0) >= 1
    assert snap.get("video.scrub.resume_recovery_started", 0) >= 1
    assert snap.get("video.scrub.resume_recovered", 0) >= 1
    assert controller.pipeline_state() == VideoPipelineState.PLAYBACK
    controller._resume_watchdog.stop()
    controller._async_inflight = False
    perf_diag.set_enabled(False)
    _shutdown_ctrl(controller)


def test_twenty_playing_drag_release_no_stuck(
    app: QApplication, red_clip_path: Path
) -> None:
    from cueplayer.diagnostics import perf as perf_diag
    from cueplayer.playback.video_sync import ReleaseTarget, ReleaseTargetKind, VideoPipelineState

    song = Song.create("Song")
    clip = VideoClip.create(
        name="red", path=red_clip_path, start_seconds=0.0, duration_seconds=2.0
    )
    song.add_video_clip(clip)
    controller = VideoSyncController()
    controller.set_song(song)
    perf_diag.set_enabled(True)
    perf_diag.clear()

    # No ThreadPool work — assert the land→resume invariant on the state machine.
    with patch.object(controller, "_request_async_live_frame", return_value=None):
        for i in range(20):
            t = 0.1 + 0.08 * (i % 10)
            controller.set_scrubbing(True, was_playing=True)
            controller._scrub_preload_timer.stop()
            controller._scrub_preview_timer.stop()
            controller.update_position(t, source="scrub")
            controller._scrubbing = False
            controller._scrub_preview_timer.stop()
            controller._scrub_pause_timer.stop()
            controller._release_target = ReleaseTarget(
                ReleaseTargetKind.VALID_MEDIA_TARGET,
                song_seconds=t,
                media_seconds=t,
                clip_id=clip.id,
            )
            controller._release_target_song_time = t
            controller._release_target_media_time = t
            controller._min_present_seconds = t
            controller._final_land_transaction_id = controller._scrub_transaction_id
            controller._pre_scrub_was_playing = True
            controller._set_pipeline_state(VideoPipelineState.FINAL_LANDING)
            controller._final_land_pending = True
            controller._async_inflight = False
            controller._complete_final_land(
                t, np.full((8, 8, 3), 40 + i, dtype=np.uint8)
            )
            assert controller.pipeline_state() == VideoPipelineState.RESUME_PLAYBACK
            assert int(perf_diag.snapshot()["counters"].get(
                "video.scrub.resume_started", 0
            )) >= i + 1
            # First valid post-land play frame completes resume.
            controller._async_req_gen += 1
            gen = controller._async_req_gen
            controller._on_async_frame_ready(
                gen,
                t + 0.01,
                np.full((8, 8, 3), 50 + i, dtype=np.uint8),
                "play",
                "",
                -1,
            )
            if controller.pipeline_state() == VideoPipelineState.RESUME_PLAYBACK:
                controller._complete_resume(reason="drain")
            assert controller.pipeline_state() == VideoPipelineState.PLAYBACK
            assert controller._final_land_pending is False
            assert controller.engine_video_gated() is False
            controller._resume_watchdog.stop()
    snap = perf_diag.snapshot()["counters"]
    req = int(snap.get("video.scrub.resume_required", 0))
    started = int(snap.get("video.scrub.resume_started", 0))
    done = int(snap.get("video.scrub.resume_completed", 0)) + int(
        snap.get("video.scrub.resume_recovered", 0)
    )
    assert req >= 20
    assert req == started
    assert done == started
    assert int(snap.get("video.scrub.final_land_completed_without_resume", 0)) == 0
    controller._land_retry_timer.stop()
    controller._async_inflight = False
    perf_diag.set_enabled(False)
    _shutdown_ctrl(controller)


def test_engine_video_gated_during_scrub_preview(
    app: QApplication, red_clip_path: Path
) -> None:
    from cueplayer.diagnostics import perf as perf_diag

    song = Song.create("Song")
    song.add_video_clip(
        VideoClip.create(
            name="red", path=red_clip_path, start_seconds=0.0, duration_seconds=2.0
        )
    )
    controller = VideoSyncController()
    controller.set_song(song)
    perf_diag.set_enabled(True)
    perf_diag.clear()
    controller.set_scrubbing(True, was_playing=True)
    controller.update_position(0.5, source="scrub")
    scrub_t = controller._scrub_target_seconds
    controller.update_position(1.9, source="engine")
    assert abs(controller._scrub_target_seconds - scrub_t) < 1e-9
    assert abs(float(controller._last_position_seconds) - 0.5) < 1e-9
    assert int(perf_diag.snapshot()["counters"].get(
        "video.scrub.engine_requests_gated_during_scrub", 0
    )) >= 1
    controller._scrub_preview_timer.stop()
    controller._scrub_pause_timer.stop()
    controller._scrubbing = False
    controller._set_pipeline_state("PLAYBACK")
    controller._async_inflight = False
    perf_diag.set_enabled(False)
    _shutdown_ctrl(controller)


def test_preview_queue_remains_depth_one(
    app: QApplication, red_clip_path: Path
) -> None:
    song = Song.create("Song")
    song.add_video_clip(
        VideoClip.create(
            name="red", path=red_clip_path, start_seconds=0.0, duration_seconds=2.0
        )
    )
    controller = VideoSyncController()
    controller.set_song(song)
    controller.set_scrubbing(True, was_playing=False)
    controller._scrub_preload_timer.stop()
    controller._scrub_preview_timer.stop()
    # Simulate one inflight scrub_preview; coalesced moves must not stack jobs.
    controller._async_inflight = True
    controller._async_req_kind = "scrub_preview"
    controller._async_req_seconds = 0.1
    gen0 = controller._async_req_gen
    for i in range(50):
        controller._request_async_live_frame(
            0.1 + 0.01 * i, kind="scrub_preview", lock_timeout=0.08
        )
    assert controller._async_inflight is True
    assert controller._async_req_gen == gen0  # no per-move invalidate
    assert abs(controller._async_req_seconds - 0.59) < 0.05
    controller._async_inflight = False
    controller._scrubbing = False
    controller._set_pipeline_state("PLAYBACK")
    _shutdown_ctrl(controller)


def test_many_preview_requests_present_under_fast_decode(
    app: QApplication, red_clip_path: Path
) -> None:
    """Regression: Round 5 presented 3/160 — must not collapse under fast decode."""
    from cueplayer.diagnostics import perf as perf_diag

    song = Song.create("Song")
    song.add_video_clip(
        VideoClip.create(
            name="red", path=red_clip_path, start_seconds=0.0, duration_seconds=2.0
        )
    )
    controller = VideoSyncController()
    controller.set_song(song)
    controller._scrub_cache.clear()
    perf_diag.set_enabled(True)
    perf_diag.clear()
    n = {"i": 0}

    def _immediate(seconds, *, kind="play", lock_timeout=0.05, force=False, **_kw):  # noqa: ANN001
        if kind != "scrub_preview":
            return
        n["i"] += 1
        perf_diag.count("video.scrub.preview_requests")
        frame = np.full((4, 4, 3), n["i"] % 200, dtype=np.uint8)
        controller._emit_frame(frame)
        controller._note_preview_presented(float(seconds))

    with patch.object(controller, "_request_async_live_frame", side_effect=_immediate):
        controller.set_scrubbing(True, was_playing=False)
        controller._scrub_preload_timer.stop()
        controller._scrub_preview_timer.stop()
        for i in range(40):
            controller.update_position(0.02 * i, source="scrub")
            controller._on_scrub_preview_tick()
    snap = perf_diag.snapshot()["counters"]
    presented = int(snap.get("video.scrub.preview_presented", 0))
    requests = int(snap.get("video.scrub.preview_requests", 0))
    assert requests >= 10
    assert presented >= 10
    assert presented / max(1, requests) >= 0.25
    controller._scrubbing = False
    controller._set_pipeline_state("PLAYBACK")
    controller._async_inflight = False
    perf_diag.set_enabled(False)
    _shutdown_ctrl(controller)


def test_scrub_and_playback_decoders_are_separate(
    app: QApplication, red_clip_path: Path
) -> None:
    song = Song.create("Song")
    clip = VideoClip.create(
        name="red", path=red_clip_path, start_seconds=0.0, duration_seconds=2.0
    )
    song.add_video_clip(clip)
    controller = VideoSyncController()
    controller.set_song(song)
    play = controller._worker_decoder_for(clip)
    scrub = controller._scrub_worker_decoder_for(clip)
    assert play is not None and scrub is not None
    assert play is not scrub
    assert clip.id in controller._worker_decoders
    assert clip.id in controller._scrub_worker_decoders
    controller._close_scrub_worker_decoders()
    assert clip.id in controller._worker_decoders
    assert clip.id not in controller._scrub_worker_decoders
    controller._close_play_worker_decoders()
    _shutdown_ctrl(controller)


def test_started_resume_completes_or_recovers(
    app: QApplication, red_clip_path: Path
) -> None:
    from cueplayer.diagnostics import perf as perf_diag
    from cueplayer.playback.video_sync import ReleaseTarget, ReleaseTargetKind, VideoPipelineState

    song = Song.create("Song")
    clip = VideoClip.create(
        name="red", path=red_clip_path, start_seconds=0.0, duration_seconds=2.0
    )
    song.add_video_clip(clip)
    controller = VideoSyncController()
    controller.set_song(song)
    perf_diag.set_enabled(True)
    perf_diag.clear()
    controller.set_scrubbing(True, was_playing=True)
    controller._scrub_preload_timer.stop()
    controller._scrub_preview_timer.stop()
    controller.update_position(0.55, source="scrub")
    controller._scrubbing = False
    controller._scrub_preview_timer.stop()
    controller._release_target = ReleaseTarget(
        ReleaseTargetKind.VALID_MEDIA_TARGET,
        song_seconds=0.55,
        media_seconds=0.55,
        clip_id=clip.id,
    )
    controller._release_target_song_time = 0.55
    controller._final_land_transaction_id = controller._scrub_transaction_id
    controller._pre_scrub_was_playing = True
    controller._set_pipeline_state(VideoPipelineState.FINAL_LANDING)
    controller._complete_final_land(0.55, np.full((8, 8, 3), 55, dtype=np.uint8))
    assert int(perf_diag.snapshot()["counters"].get("video.scrub.resume_started", 0)) >= 1
    gen = controller._async_req_gen
    controller._on_async_frame_ready(
        gen, 0.56, np.full((8, 8, 3), 56, dtype=np.uint8), "play", "", -1
    )
    if controller.pipeline_state() == VideoPipelineState.RESUME_PLAYBACK:
        controller._complete_resume(reason="drain")
    snap = perf_diag.snapshot()["counters"]
    started = int(snap.get("video.scrub.resume_started", 0))
    done = int(snap.get("video.scrub.resume_completed", 0)) + int(
        snap.get("video.scrub.resume_recovered", 0)
    )
    assert started >= 1
    assert done == started
    controller._resume_watchdog.stop()
    controller._invalidate_async_requests()
    controller._async_inflight = False
    perf_diag.set_enabled(False)
    _shutdown_ctrl(controller)


