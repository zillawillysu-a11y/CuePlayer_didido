"""Deterministic MTC deadline scheduler and sender-lifecycle regressions."""

from __future__ import annotations

import math
import threading

import pytest

from cueplayer.domain.models import AudioOutputSettings, Mark, MarkLane, Song
from cueplayer.playback.audio_engine import AudioEngine
from cueplayer.playback.mtc_output import MtcOutput


class _Port:
    def __init__(self) -> None:
        self.messages: list = []

    def send(self, message) -> None:
        self.messages.append(message)

    def close(self) -> None:
        pass


def _armed_output(fps: float) -> tuple[MtcOutput, _Port]:
    output = MtcOutput()
    port = _Port()
    output._port = port
    output._enabled = True
    output.set_timebase("01:02:03:04", fps)
    output.on_play(0.0)
    port.messages.clear()
    return output, port


def _quarter_frames(port: _Port) -> list:
    return [m for m in port.messages if m.type == "quarter_frame"]


@pytest.mark.parametrize("fps", [24.0, 25.0, 29.97, 30.0])
def test_deadlines_emit_exact_qf_order_without_duplicate_or_skip(fps: float) -> None:
    output, port = _armed_output(fps)
    qf_rate = fps * 4.0
    try:
        for index in range(24):
            position = 0.0 if index == 0 else (index / qf_rate) + 1e-12
            output.tick(position)
            assert output.seconds_until_next_quarter_frame(position) == pytest.approx(
                ((index + 1) / qf_rate) - position,
                abs=1e-10,
            )
        messages = _quarter_frames(port)
        assert len(messages) == 24
        assert [message.frame_type for message in messages] == [
            index % 8 for index in range(24)
        ]
    finally:
        output.close()


@pytest.mark.parametrize("fps", [24.0, 25.0, 29.97, 30.0])
def test_controlled_old_polling_vs_deadline_schedule_has_same_messages(
    fps: float,
) -> None:
    """Compare pre/post pacing against the same fake sample clock."""
    duration = 1.0
    old, old_port = _armed_output(fps)
    new, new_port = _armed_output(fps)
    try:
        old_positions = [step * 0.004 for step in range(251)]
        deadline_positions = [
            0.0,
            *[
                (index / (fps * 4.0)) + 1e-12
                for index in range(1, math.floor(duration * fps * 4.0) + 1)
            ],
        ]
        for position in old_positions:
            old.tick(position)
        for position in deadline_positions:
            new.tick(position)

        old_bytes = [bytes(message.bytes()) for message in _quarter_frames(old_port)]
        new_bytes = [bytes(message.bytes()) for message in _quarter_frames(new_port)]
        assert old_bytes == new_bytes
        assert len(old_positions) == 251
        assert len(deadline_positions) == math.floor(fps * 4.0) + 1
        assert len(new_bytes) == len(deadline_positions)
    finally:
        old.close()
        new.close()


def test_next_cue_note_deadline_replaces_fixed_polling() -> None:
    engine = AudioEngine()
    song = Song.create("Deadline notes")
    song.mark_lanes = [
        MarkLane(index=1, name="Main", lane_type="main", midi_note_enabled=True)
    ]
    song.marks = [Mark.create(1, 12.5)]
    engine._midi_cues.configure(enabled=True, port_name="")
    engine._midi_cues.set_song(song)
    engine._midi_cues.on_play(10.0)
    assert engine._midi_cues.seconds_until_next_note(10.0) == pytest.approx(2.5)
    engine._midi_cues.on_seek(13.0)
    assert engine._midi_cues.seconds_until_next_note(13.0) is None


def test_blocked_generation_cannot_spawn_duplicate_sender(monkeypatch) -> None:
    from cueplayer.playback import audio_engine as module

    engine = AudioEngine()
    entered = threading.Event()
    release = threading.Event()

    def blocked_tick(generation=None):
        del generation
        entered.set()
        release.wait(timeout=1.0)
        return None

    monkeypatch.setattr(module, "_MTC_JOIN_TIMEOUT_SECONDS", 0.01)
    monkeypatch.setattr(engine, "_mtc_tick", blocked_tick)
    engine._start_mtc_thread()
    assert entered.wait(timeout=1.0)
    first = engine._mtc_thread

    engine._stop_mtc_thread()
    assert first is not None and first.is_alive()
    engine._start_mtc_thread()
    assert engine._mtc_thread is first
    assert engine.mtc_timing_diagnostics()["sender_start_count"] == 1

    release.set()
    first.join(timeout=1.0)
    assert not first.is_alive()
    engine._start_mtc_thread()
    second = engine._mtc_thread
    assert second is not None and second is not first
    engine._stop_mtc_thread()
    second.join(timeout=1.0)

    diag = engine.mtc_timing_diagnostics()
    assert diag["sender_start_count"] == 2
    assert diag["sender_stop_count"] == 2
    assert diag["live_sender_count"] == 0
    assert diag["duplicate_live_sender_count"] == 0
    assert diag["duplicate_live_sender_peak"] == 0


def test_stale_generation_cannot_send_after_stop() -> None:
    engine = AudioEngine()
    port = _Port()
    engine._mtc._port = port
    engine._mtc._enabled = True
    engine._playing = True
    engine._mtc.on_play(0.0)
    port.messages.clear()
    engine._mtc_thread_generation = 7
    engine._mtc_active_generation = 0

    assert engine._mtc_tick(generation=7) is None
    assert port.messages == []


@pytest.mark.parametrize("fps", [24.0, 25.0, 29.97, 30.0])
def test_pause_resume_and_seek_reanchor_without_stale_qf(fps: float) -> None:
    output, port = _armed_output(fps)
    qf_rate = fps * 4.0
    try:
        output.tick(0.0)
        assert [message.frame_type for message in _quarter_frames(port)] == [0]

        output.on_pause()
        output.tick(10.0)
        assert [message.frame_type for message in _quarter_frames(port)] == [0]

        output.on_play(2.0)
        port.messages.clear()  # discard the intentional full-frame re-anchor
        output.tick(2.0)
        expected = int(2.0 * qf_rate) % 8
        assert [message.frame_type for message in _quarter_frames(port)] == [expected]

        output.on_seek(4.0, playing=True)
        port.messages.clear()  # discard the intentional full-frame re-anchor
        output.tick(4.0)
        expected = int(4.0 * qf_rate) % 8
        assert [message.frame_type for message in _quarter_frames(port)] == [expected]
    finally:
        output.close()


def test_repeated_start_stop_has_one_live_sender_and_monotonic_generations() -> None:
    engine = AudioEngine()
    try:
        for expected_generation in range(1, 4):
            engine._start_mtc_thread()
            engine._start_mtc_thread()
            diag = engine.mtc_timing_diagnostics()
            assert diag["thread_generation_id"] == expected_generation
            assert diag["sender_start_count"] == expected_generation
            assert diag["duplicate_live_sender_count"] == 0
            engine._stop_mtc_thread()
            assert engine._mtc_thread is None
        diag = engine.mtc_timing_diagnostics()
        assert diag["sender_stop_count"] == 3
        assert diag["duplicate_live_sender_peak"] == 0
    finally:
        engine.shutdown_midi_outputs()


def test_song_switch_and_seek_wake_deadline_sender() -> None:
    engine = AudioEngine()
    wake = threading.Event()
    engine._mtc_thread_wake = wake
    engine.set_song(Song.create("下一首"))
    assert wake.is_set()
    wake.clear()
    engine.seek(1.0)
    assert wake.is_set()


def test_play_pause_resume_stop_own_exactly_one_sender() -> None:
    engine = AudioEngine()
    engine._audio_settings = AudioOutputSettings(
        midi_enabled=True,
        mtc_enabled=True,
    )
    try:
        engine.play()
        assert engine.mtc_timing_diagnostics()["live_sender_count"] <= 1
        engine.pause()
        assert engine._mtc_thread is None

        engine.play()
        assert engine.mtc_timing_diagnostics()["thread_generation_id"] == 2
        engine.stop()
        assert engine._mtc_thread is None
        assert engine.mtc_timing_diagnostics()["duplicate_live_sender_peak"] == 0
    finally:
        engine.shutdown_midi_outputs()


def test_reconfigure_and_device_switch_leave_no_stale_sender(monkeypatch) -> None:
    engine = AudioEngine()
    monkeypatch.setattr(engine, "_resolve_device_and_route", lambda: None)
    monkeypatch.setattr(engine, "_rebuild_output_stream", lambda: None)
    monkeypatch.setattr(engine, "_ensure_stream", lambda: True)
    monkeypatch.setattr(engine, "_needs_output_stream", lambda: False)
    on = AudioOutputSettings(midi_enabled=True, mtc_enabled=True)
    off = AudioOutputSettings(midi_enabled=False, mtc_enabled=False)
    try:
        engine._audio_settings = on
        engine.play()
        engine.apply_audio_settings(off)
        assert engine._mtc_thread is None

        engine.apply_audio_settings(on)
        assert engine.mtc_timing_diagnostics()["live_sender_count"] <= 1
        engine.apply_audio_settings(
            AudioOutputSettings(
                output_device_name="Focusrite DirectSound",
                output_hostapi="Windows DirectSound",
                midi_enabled=True,
                mtc_enabled=True,
            )
        )
        diag = engine.mtc_timing_diagnostics()
        assert diag["duplicate_live_sender_count"] == 0
        assert diag["duplicate_live_sender_peak"] == 0
    finally:
        engine.shutdown_midi_outputs()
