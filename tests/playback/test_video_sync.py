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
    controller.update_position(2.5)

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
    """Outside a scrub, every call decodes immediately (unthrottled) — this is what
    keeps normal playback frame-accurate. While scrubbing, rapid-fire calls (as the
    timeline emits on every mouse-move) should collapse to far fewer actual decodes,
    which is the fix for drag lag once a video clip is on the timeline."""
    song = Song.create("Song")
    clip = VideoClip.create(name="red", path=red_clip_path, start_seconds=0.0, duration_seconds=2.0)
    song.add_video_clip(clip)

    controller = VideoSyncController()
    controller.set_song(song)
    frames: list[object] = []
    controller.frame_changed.connect(frames.append)

    controller.set_scrubbing(True)
    for i in range(20):
        controller.update_position(0.01 * i)
    # 20 calls fired back-to-back (sub-millisecond apart) must not all decode.
    assert len(frames) < 20

    controller.set_scrubbing(False)  # flush: the last requested position must land.
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
    controller.update_position(0.1)  # decodes immediately (first call)
    controller.update_position(2.5)  # thrown right after: throttled, pending
    controller.set_scrubbing(False)  # must flush the *last* requested position

    assert len(frames) >= 2
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


def test_playback_decode_rate_stays_near_display_refresh_cap(
    app: QApplication, red_clip_path: Path
) -> None:
    """Direct proof the play path is bounded to roughly the ~30fps playback
    cap (VideoSyncController._MAX_PLAY_DECODE_HZ / _MIN_PLAY_DECODE_INTERVAL)
    rather than the position-tick rate: hammer update_position() as fast as
    Python can for a fixed wall-clock window and assert the number of frames
    actually decoded+emitted is close to `window * 30fps`, not the (much
    larger) number of calls made."""
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
    max_expected_frames = int(window_seconds * 30.0) + 3  # + slack for scheduling jitter
    assert len(frames) <= max_expected_frames


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

    controller.update_position(0.1)
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
    controller.update_position(0.3)
    controller.update_position(1.2)

    assert len(frames) >= 1
    assert all(isinstance(f, np.ndarray) for f in frames if f is not None)
    # Mid-scrub must not have opened the live decoder.
    assert clip.id not in controller._decoders

    controller.set_scrubbing(False)
    # Mouse-up flush may open the live decoder for the exact land frame.
    assert clip.id in controller._decoders
