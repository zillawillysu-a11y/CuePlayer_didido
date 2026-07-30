"""Hardening: VideoDecoder.close serializes with decode; no callback resample."""

from __future__ import annotations

import threading
from pathlib import Path
from unittest.mock import MagicMock

import numpy as np
import pytest

pytest.importorskip("PySide6")

from cueplayer.media.av_lock import av_path_lock
from cueplayer.media.video_loader import VideoDecoder
from cueplayer.playback.audio_engine import AudioEngine


def test_video_decoder_close_waits_for_path_lock(tmp_path: Path, monkeypatch) -> None:
    """close() must take av_path_lock so it cannot race another demux on the path."""
    media = tmp_path / "clip.mov"
    media.write_bytes(b"fake")

    held = threading.Event()
    release = threading.Event()
    closed = threading.Event()
    order: list[str] = []

    class _FakeContainer:
        def close(self) -> None:
            order.append("close")

    decoder = object.__new__(VideoDecoder)
    decoder._path = media
    decoder._closed = False
    decoder._container = _FakeContainer()
    decoder._iterator = iter(())
    decoder._last_frame = None
    decoder._last_pts_seconds = None
    decoder._pending_frame = None
    decoder._pending_pts_seconds = None
    decoder._cached_ndarray = None
    decoder._cached_ndarray_source = None

    def _hold() -> None:
        with av_path_lock(media):
            order.append("hold-enter")
            held.set()
            assert release.wait(2.0)
            order.append("hold-exit")

    t = threading.Thread(target=_hold)
    t.start()
    assert held.wait(2.0)

    def _close() -> None:
        decoder.close()
        order.append("closed")
        closed.set()

    closer = threading.Thread(target=_close)
    closer.start()
    # close must block while the path lock is held
    assert not closed.wait(0.05)
    release.set()
    closer.join(2.0)
    t.join(2.0)
    assert decoder._closed
    assert order.index("hold-enter") < order.index("hold-exit")
    assert order.index("hold-exit") < order.index("close")
    assert order.index("close") < order.index("closed")


def test_source_channel_chunk_uses_pre_resampled_pcm_on_rate_mismatch() -> None:
    from cueplayer.media.audio_loader import AudioBuffer

    engine = AudioEngine()
    samples = np.zeros((4800, 2), dtype=np.float32)
    buf = AudioBuffer(
        path=Path("/fake.wav"),
        sample_rate=44100,
        samples=samples,
        mono=samples[:, 0],
        peak_levels=[],
    )
    engine._buffer = buf
    engine._playback_rate = 48000
    resampled = np.linspace(0.0, 1.0, 5200, dtype=np.float32)
    engine._playback_samples = np.column_stack([resampled, resampled])
    engine._is_ltc_file_channel = lambda _ch: True  # type: ignore[method-assign]

    out = engine._source_channel_chunk(0, 0, 128)
    assert out.shape == (128,)
    np.testing.assert_allclose(out, resampled[:128])
    engine.shutdown_midi_outputs()


def test_quiesce_output_stops_stream(monkeypatch) -> None:
    engine = AudioEngine()
    stream = MagicMock()
    engine._stream = stream
    engine._playing = True
    engine._position_frame = 1000

    engine.quiesce_output()

    assert engine.playing is False
    assert engine._stream is None
    stream.stop.assert_called_once()
    stream.close.assert_called_once()
    engine.shutdown_midi_outputs()
