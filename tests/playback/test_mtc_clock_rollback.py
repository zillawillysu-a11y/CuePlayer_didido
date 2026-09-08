"""MTC must distinguish an interpolated-clock correction from a transport seek."""

import pytest

from cueplayer.playback.mtc_output import MtcOutput


class Port:
    def __init__(self):
        self.messages = []

    def send(self, message):
        self.messages.append(message)

    def close(self):
        pass


def arm(fps=30.0, position=1.0):
    mtc = MtcOutput()
    mtc._port = Port()
    mtc._enabled = True
    mtc.set_timebase("01:00:00:00", fps)
    mtc.on_play(position)
    mtc._port.messages.clear()
    return mtc


@pytest.mark.parametrize("fps", [24.0, 25.0, 29.97, 30.0])
def test_callback_clock_correction_does_not_send_locate_or_repeat_qf(fps):
    mtc = arm(fps)
    try:
        # Successive callback sample heads remain strictly increasing:
        # 1.000 -> 1.015 -> 1.030.  Between callbacks raw_position adds
        # elapsed wall time. A callback arriving 25 ms later but advancing
        # 15 ms of samples corrects the extrapolated value backwards.
        positions = [1.000, 1.009, 1.018, 1.024, 1.015, 1.024, 1.030, 1.039]
        for position in positions:
            mtc.tick(position)
        messages = mtc._port.messages
        assert not any(m.type == "sysex" for m in messages)
        indices = range(int(1.0 * fps * 4), int(1.039 * fps * 4) + 1)
        assert [m.frame_type for m in messages] == [i % 8 for i in indices]
    finally:
        mtc.close()


@pytest.mark.parametrize("destination", [0.999, 0.5, 5.0])
def test_explicit_seek_still_locates_even_for_one_millisecond(destination):
    mtc = arm()
    try:
        mtc.tick(1.020)
        mtc._port.messages.clear()
        mtc.on_seek(destination, playing=True)
        mtc.tick(destination)
        assert sum(m.type == "sysex" for m in mtc._port.messages) == 1
        qf = [m for m in mtc._port.messages if m.type == "quarter_frame"]
        assert qf[0].frame_type == int(destination * 120) % 8
    finally:
        mtc.close()


def test_late_tick_still_bounds_forward_backlog():
    mtc = arm()
    try:
        mtc.tick(1.0)
        mtc._port.messages.clear()
        mtc.tick(10.0)
        assert sum(m.type == "sysex" for m in mtc._port.messages) == 1
        assert len(mtc._port.messages) <= 9
    finally:
        mtc.close()


def test_clip_boundary_skip_does_not_repeatedly_locate_until_next_group():
    from cueplayer.timecode.mtc import absolute_timecode
    from cueplayer.timecode.smpte import Timecode

    mtc = arm()
    mtc.set_tc_provider(lambda pos: absolute_timecode(
        Timecode(1 if pos < 1.015 else 2, 0, 0, 0), pos, 30.0
    ))
    try:
        mtc.on_seek(1.020, playing=True)
        mtc._port.messages.clear()
        # Group starts at 1.000 in the old mapping, but current TC is in
        # the new clip. Skip its remaining pieces and send one locate.
        mtc.tick(1.020)
        assert sum(m.type == "sysex" for m in mtc._port.messages) == 1
        mtc._port.messages.clear()
        for position in (1.030, 1.040, 1.050, 1.060):
            mtc.tick(position)
        assert mtc._port.messages == []
        mtc.tick(1.067)
        assert [m.frame_type for m in mtc._port.messages] == [0]
    finally:
        mtc.close()


def test_diagnostics_separate_clock_correction_locates_and_qf_gap(monkeypatch):
    from cueplayer.playback import mtc_output as module

    now = [10.0]
    monkeypatch.setattr(module.time, "perf_counter", lambda: now[0])
    monkeypatch.setattr(module.perf_diag, "_enabled", True)
    mtc = arm()
    try:
        mtc.reset_timing_diagnostics()
        mtc.tick(1.0)
        now[0] += 0.010
        mtc.tick(1.010)
        now[0] += 0.003
        mtc.tick(1.001)
        snap = mtc.timing_diagnostics()
        assert snap["clock_backward_count"] == 1
        assert snap["clock_backward_max_ms"] == pytest.approx(9.0)
        assert snap["qf_send_count"] == 2
        assert snap["qf_gap_max_ms"] == pytest.approx(10.0)
        assert snap["full_frame_count"] == 0
        mtc.on_seek(0.5, playing=True)
        assert mtc.timing_diagnostics()["full_frame_seek_or_source_count"] == 1
        mtc.tick(5.0)
        assert mtc.timing_diagnostics()["full_frame_overdue_count"] == 1
        mtc.reset_timing_diagnostics()
        snap = mtc.timing_diagnostics()
        assert snap["qf_send_count"] == snap["full_frame_count"] == 0
        assert snap["clock_backward_count"] == 0
    finally:
        mtc.close()


def test_failed_midi_send_is_not_counted_as_successful_qf(monkeypatch):
    from cueplayer.playback import mtc_output as module

    monkeypatch.setattr(module.perf_diag, "_enabled", True)
    mtc = arm()
    try:
        mtc.reset_timing_diagnostics()

        def fail(message):
            raise OSError("test port failure")

        mtc._port.send = fail
        mtc.tick(1.0)
        snap = mtc.timing_diagnostics()
        assert snap["send_error_count"] == 1
        assert snap["qf_send_count"] == 0
    finally:
        mtc.close()
