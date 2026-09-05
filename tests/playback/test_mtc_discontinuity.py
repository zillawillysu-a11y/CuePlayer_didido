from cueplayer.playback.mtc_output import MtcOutput
from cueplayer.playback.audio_engine import AudioEngine
import numpy as np


class Port:
    def __init__(self): self.messages = []
    def send(self, message): self.messages.append(message)
    def close(self): pass


def output():
    mtc = MtcOutput()
    mtc._port = Port()
    mtc._enabled = True
    mtc.on_play(10)
    mtc._port.messages.clear()
    return mtc


def test_backwards_jump_resumes_quarter_frames_immediately():
    mtc = output()
    try:
        mtc.tick(10)
        mtc._port.messages.clear()
        mtc.tick(2)
        assert any(m.bytes()[0] == 0xF0 for m in mtc._port.messages)
        assert any(m.bytes()[0] == 0xF1 for m in mtc._port.messages)
    finally:
        mtc.close()


def test_long_ui_stall_does_not_burst_thousands_of_expired_messages():
    mtc = output()
    try:
        mtc.tick(100)
        assert len(mtc._port.messages) <= 9
        assert any(m.bytes()[0] == 0xF0 for m in mtc._port.messages)
    finally:
        mtc.close()


def test_natural_loop_signals_reset_even_if_new_position_is_higher(monkeypatch):
    engine = AudioEngine()
    engine._playback_rate = 48000
    engine._playing = True
    engine.loop_a, engine.loop_b = 0, .01
    engine.loop_enabled = engine._loop_engage = True
    engine._playback_samples = np.zeros((48000, 2), np.float32)
    resets = []
    monkeypatch.setattr(engine._mtc, 'on_seek', lambda pos, **kw: resets.append(pos))
    # More than two loops, yet final frame 64 is greater than previous frame 0.
    engine._make_stream_callback(48000)(np.zeros((1024, 2), np.float32), 1024, None, None)
    engine._mtc_tick()
    assert len(resets) == 1
    engine._mtc_tick()
    assert len(resets) == 1
