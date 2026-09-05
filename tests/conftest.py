"""Unit tests never start native audio callback threads.

Device/driver integration requires a separate, explicit hardware harness. Tests
may override OutputStream to exercise rejection, negotiation and callbacks.
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("SD_ENABLE_ASIO", "1")

import pytest


class FakeOutputStream:
    def __init__(self, **kwargs):
        self.samplerate = kwargs.get("samplerate", 48000)
        self.channels = kwargs.get("channels", 2)
        self.callback = kwargs.get("callback")
        self.latency = 0.01
        self.active = False
        self.closed = False

    def start(self):
        self.active = True
        return self

    def stop(self):
        self.active = False

    def abort(self):
        self.stop()

    def close(self):
        self.stop()
        self.closed = True

    def __enter__(self):
        return self.start()

    def __exit__(self, *args):
        self.close()


@pytest.fixture(scope="session", autouse=True)
def retained_qapplication():
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture(autouse=True)
def isolated_audio_engines(monkeypatch, retained_qapplication):
    import sounddevice as sd
    from cueplayer.playback.audio_engine import AudioEngine
    from cueplayer.playback.video_sync import VideoSyncController

    monkeypatch.setattr(sd, "OutputStream", FakeOutputStream)
    engines = []
    controllers = []
    original_init = AudioEngine.__init__

    def initialize(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        engines.append(self)

    monkeypatch.setattr(AudioEngine, "__init__", initialize)
    original_video_init = VideoSyncController.__init__

    def initialize_video(self, *args, **kwargs):
        original_video_init(self, *args, **kwargs)
        controllers.append(self)

    monkeypatch.setattr(VideoSyncController, "__init__", initialize_video)
    yield
    # Hold QObject wrappers until all jobs that can signal them have completed.
    # This is test cleanup, not a substitute for production lifecycle fixes.
    import shiboken6

    for controller in controllers:
        controller.shutdown()
        controller._async_pool.shutdown(wait=True, cancel_futures=True)
    for engine in engines:
        if shiboken6.isValid(engine):
            for timer in (engine._poll, engine._silent_timer, engine._mtc_timer):
                timer.stop()
        engine._playing = False
        engine._stop_stream()
        engine.shutdown_midi_outputs()
        for executor in (engine._ltc_executor, engine._resample_executor,
                         engine._ltc_detect_executor, engine._video_mixer._executor):
            executor.shutdown(wait=True, cancel_futures=True)
