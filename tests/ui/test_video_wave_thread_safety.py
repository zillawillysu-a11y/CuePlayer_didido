"""Video clip waveform ready callback must not touch Qt from a worker thread."""

from __future__ import annotations

import threading
from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QCoreApplication, Qt, QThread
from PySide6.QtWidgets import QApplication

from cueplayer.domain.models import Song, VideoClip
from cueplayer.media.video_clip_waveform import VideoClipWaveformCache
from cueplayer.ui.timeline_widget import TimelineWidget


@pytest.fixture
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_waveform_ready_marshals_to_gui_thread(app: QApplication) -> None:
    widget = TimelineWidget()
    widget.resize(400, 300)
    gui_thread = QThread.currentThread()
    seen: list[QThread | None] = []

    def _capture() -> None:
        seen.append(QThread.currentThread())

    widget._video_waveforms_ready.disconnect()
    widget._video_waveforms_ready.connect(_capture, Qt.ConnectionType.QueuedConnection)

    worker_done = threading.Event()
    worker_idents: list[int] = []

    def _worker() -> None:
        worker_idents.append(threading.get_ident())
        widget._on_video_waveform_ready()
        worker_done.set()

    t = threading.Thread(target=_worker, name="fake-vid-wave")
    t.start()
    assert worker_done.wait(2.0)
    t.join(2.0)

    for _ in range(50):
        QCoreApplication.processEvents()
        if seen:
            break

    assert worker_idents
    assert worker_idents[0] != threading.get_ident()
    assert seen == [gui_thread]


def test_waveform_cache_clear_drops_stale_result(app: QApplication, tmp_path: Path) -> None:
    del app
    cache = VideoClipWaveformCache()
    media = tmp_path / "clip.mov"
    media.write_bytes(b"fake")
    clip = VideoClip.create(
        path=media,
        name="Clip",
        start_seconds=0.0,
        duration_seconds=1.0,
        media_kind="video",
    )
    key = cache.key_for(clip)
    cache.clear()
    gen_before = cache._generation
    cache._build_async(gen_before - 1, key, clip)
    assert key not in cache._peaks


def test_toggle_video_eye_does_not_recurse(app: QApplication) -> None:
    song = Song.create("Vid")
    widget = TimelineWidget()
    widget.set_song(song)
    widget.resize(640, 400)
    widget.set_show_video_track(False, emit=False)
    widget.set_show_video_track(True, emit=True)
    assert widget._show_video_track is True
    widget.set_show_video_track(False, emit=True)
    assert widget._show_video_track is False
