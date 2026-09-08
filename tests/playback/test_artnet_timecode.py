from __future__ import annotations

import time

import pytest

from cueplayer.diagnostics import perf as perf_diag
from cueplayer.playback import artnet_timecode as artnet
from cueplayer.playback.artnet_timecode import (
    ARTNET_PORT,
    ArtNetTimecodeOutput,
    Ipv4Interface,
    artnet_timecode_at,
    artnet_timecode_type,
    build_art_timecode_packet,
    validate_artnet_destination,
)
from cueplayer.playback.mtc_output import MtcOutput
from cueplayer.timecode.smpte import Timecode


class _Socket:
    def __init__(self) -> None:
        self.blocking: bool | None = None
        self.options: list[tuple[int, int, int]] = []
        self.bound: tuple[str, int] | None = None
        self.sent: list[tuple[bytes, tuple[str, int]]] = []
        self.closed = False

    def setblocking(self, flag: bool) -> None:
        self.blocking = flag

    def setsockopt(self, level: int, option: int, value: int) -> None:
        self.options.append((level, option, value))

    def bind(self, address: tuple[str, int]) -> None:
        self.bound = address

    def sendto(self, data: bytes, address: tuple[str, int]) -> int:
        self.sent.append((data, address))
        return len(data)

    def close(self) -> None:
        self.closed = True


class _MidiPort:
    def __init__(self) -> None:
        self.messages: list = []

    def send(self, message) -> None:
        self.messages.append(message)

    def close(self) -> None:
        pass


def test_official_arttimecode_packet_field_vector() -> None:
    packet = build_art_timecode_packet(Timecode(1, 2, 3, 4), 30.0)
    assert packet == bytes.fromhex(
        "41 72 74 2d 4e 65 74 00 "
        "00 97 "
        "00 0e "
        "00 00 "
        "04 03 02 01 03"
    )
    assert len(packet) == 19


@pytest.mark.parametrize(
    ("fps", "type_value", "max_frame"),
    [(24.0, 0, 23), (25.0, 1, 24), (29.97, 2, 29), (30.0, 3, 29)],
)
def test_official_type_values_and_frame_ranges(
    fps: float, type_value: int, max_frame: int
) -> None:
    assert artnet_timecode_type(fps) == type_value
    packet = build_art_timecode_packet(Timecode(23, 59, 59, max_frame), fps)
    assert packet[14:19] == bytes((max_frame, 59, 59, 23, type_value))


def test_2997_drop_frame_boundaries() -> None:
    frame_seconds = 1_001.0 / 30_000.0
    assert artnet_timecode_at("00:00:00:00", 1_799 * frame_seconds, 29.97) == Timecode(
        0, 0, 59, 29
    )
    assert artnet_timecode_at("00:00:00:00", 1_800 * frame_seconds, 29.97) == Timecode(
        0, 1, 0, 2
    )
    assert artnet_timecode_at("00:00:00:00", 17_982 * frame_seconds, 29.97) == Timecode(
        0, 10, 0, 0
    )


def test_2997_rejects_nonexistent_drop_frame_label() -> None:
    with pytest.raises(ValueError, match="frames 00 and 01"):
        artnet_timecode_at("00:01:00:00", 0.0, 29.97)


def test_broadcast_validation_uses_selected_interface_directed_address(monkeypatch) -> None:
    monkeypatch.setattr(
        artnet,
        "list_ipv4_interfaces",
        lambda: [Ipv4Interface("Art-Net", "2.0.0.233", "255.0.0.0", "2.255.255.255")],
    )
    assert validate_artnet_destination(
        "2.0.0.233", "broadcast", "2.255.255.255"
    ) == ("2.0.0.233", "broadcast", "2.255.255.255")
    with pytest.raises(ValueError, match="must be 2.255.255.255"):
        validate_artnet_destination("2.0.0.233", "broadcast", "2.0.0.99")
    with pytest.raises(ValueError, match="forbids"):
        validate_artnet_destination("2.0.0.233", "broadcast", "255.255.255.255")


def test_sender_binds_official_port_and_sets_broadcast() -> None:
    udp = _Socket()
    snapshot = (0, 0, 1.0, False, False, 48_000, 0)
    sender = ArtNetTimecodeOutput(lambda: snapshot, socket_factory=lambda *_: udp)
    try:
        # No matching real interface in this synthetic test means only the
        # protocol-level limited-broadcast prohibition is applied.
        error = sender.configure(
            enabled=True,
            fps=30.0,
            start_timecode="01:00:00:00",
            local_ip="192.0.2.10",
            destination_mode="broadcast",
            destination_ip="192.0.2.255",
        )
        assert error is None
        assert udp.blocking is False
        assert udp.bound == ("192.0.2.10", ARTNET_PORT)
        assert any(option == artnet.socket.SO_BROADCAST for _, option, _ in udp.options)
    finally:
        sender.close()


def test_sender_lifecycle_is_idempotent_and_seek_sends_current_frame() -> None:
    udp = _Socket()
    clock = {"snapshot": (0, 0, time.monotonic(), False, False, 48_000, 0)}
    sender = ArtNetTimecodeOutput(
        lambda: clock["snapshot"], socket_factory=lambda *_: udp
    )
    perf_diag.set_enabled(True)
    perf_diag.clear()
    try:
        assert sender.configure(
            enabled=True,
            fps=30.0,
            start_timecode="01:00:00:00",
            local_ip="127.0.0.1",
            destination_mode="unicast",
            destination_ip="127.0.0.1",
        ) is None
        now = time.monotonic()
        clock["snapshot"] = (0, 0, now, True, False, 48_000, 0)
        sender.on_play()
        first_thread = sender._thread
        sender.on_play()
        assert sender._thread is first_thread
        time.sleep(0.05)
        assert udp.sent

        now = time.monotonic()
        clock["snapshot"] = (48_000, 48_000, now, True, False, 48_000, 1)
        sender.on_seek(playing=True)
        deadline = time.monotonic() + 0.25
        while time.monotonic() < deadline and udp.sent[-1][0][15] != 1:
            time.sleep(0.005)
        assert udp.sent[-1][0][14:19] == bytes((0, 1, 0, 1, 3))

        sender.on_pause()
        sent_at_pause = len(udp.sent)
        time.sleep(0.04)
        assert len(udp.sent) == sent_at_pause
        assert sender.running is False
        assert perf_diag.snapshot()["attrs"]["artnet_tc.duplicate_live_sender_count"] == 0
    finally:
        sender.close()
        perf_diag.set_enabled(False)
        perf_diag.clear()


def test_artnet_30fps_and_mtc_120qf_share_position_without_coupling() -> None:
    """Both outputs consume one sample position at their independent cadences."""
    udp = _Socket()
    clock = {"snapshot": (0, 0, 0.0, True, False, 48_000, 0)}
    artnet_sender = ArtNetTimecodeOutput(
        lambda: clock["snapshot"], socket_factory=lambda *_: udp
    )
    midi_port = _MidiPort()
    mtc = MtcOutput()
    perf_diag.set_enabled(True)
    perf_diag.clear()
    try:
        assert artnet_sender.configure(
            enabled=True,
            fps=30.0,
            start_timecode="01:00:00:00",
            local_ip="127.0.0.1",
            destination_mode="unicast",
            destination_ip="127.0.0.1",
        ) is None
        artnet_sender._playing = True
        mtc._port = midi_port
        mtc._enabled = True
        mtc._fps = 30.0
        mtc.on_play(0.0)
        midi_port.messages.clear()

        base = 100.0
        for qf_index in range(121):
            position = qf_index / 120.0
            frame = int(round(position * 48_000))
            clock["snapshot"] = (frame, frame, 0.0, True, False, 48_000, 0)
            mtc.tick(position)
            artnet_sender._tick_once(base + position)

        quarter_frames = [
            message for message in midi_port.messages if message.type == "quarter_frame"
        ]
        assert 120 <= len(quarter_frames) <= 121
        assert 30 <= len(udp.sent) <= 31
        snap = perf_diag.snapshot()
        assert snap["attrs"]["artnet_tc.sends_per_second"] == pytest.approx(30.0)
        assert snap["counters"].get("artnet_tc.send_failures", 0) == 0
        assert snap["counters"].get("mtc.qf_send_failures", 0) == 0
        report = perf_diag.report_text()
        assert "Art-Net Timecode continuity:" in report
        assert "artnet_tc.send_count" in report
        assert "artnet_tc.wakeup_lateness_ms" in report
    finally:
        artnet_sender.close()
        mtc.close()
        perf_diag.set_enabled(False)
        perf_diag.clear()
