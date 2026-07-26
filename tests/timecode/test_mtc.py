"""MTC quarter-frame unit tests."""

from __future__ import annotations

from cueplayer.timecode.mtc import (
    absolute_timecode,
    full_frame_sysex,
    mtc_rate_code,
    quarter_frame_messages,
    quarter_frame_payload,
)
from cueplayer.timecode.smpte import Timecode


def test_mtc_rate_codes() -> None:
    assert mtc_rate_code(24.0) == 0
    assert mtc_rate_code(25.0) == 1
    assert mtc_rate_code(30.0) == 3
    assert mtc_rate_code(29.97) == 3


def test_quarter_frame_sequence_known_tc() -> None:
    # 01:02:03:04 @ 30 fps
    tc = Timecode(1, 2, 3, 4)
    msgs = quarter_frame_messages(tc, 30.0)
    assert len(msgs) == 8
    assert all(status == 0xF1 for status, _ in msgs)

    # type 0: frames LS = 4
    assert msgs[0][1] == ((0 << 4) | 0x4)
    # type 1: frames MS = 0
    assert msgs[1][1] == ((1 << 4) | 0x0)
    # type 2: seconds LS = 3
    assert msgs[2][1] == ((2 << 4) | 0x3)
    # type 3: seconds MS = 0
    assert msgs[3][1] == ((3 << 4) | 0x0)
    # type 4: minutes LS = 2
    assert msgs[4][1] == ((4 << 4) | 0x2)
    # type 5: minutes MS = 0
    assert msgs[5][1] == ((5 << 4) | 0x0)
    # type 6: hours LS = 1
    assert msgs[6][1] == ((6 << 4) | 0x1)
    # type 7: hours MS (0) + rate 30 (3 << 1)
    assert msgs[7][1] == ((7 << 4) | ((3 & 0x03) << 1))


def test_quarter_frame_payload_helpers() -> None:
    tc = Timecode(10, 20, 30, 15)
    assert quarter_frame_payload(tc, 0, 25.0) & 0x0F == 0xF
    assert quarter_frame_payload(tc, 1, 25.0) & 0x0F == 0x0
    assert (quarter_frame_payload(tc, 7, 25.0) >> 1) & 0x03 == 1  # 25 fps


def test_full_frame_sysex() -> None:
    tc = Timecode(1, 2, 3, 4)
    sx = full_frame_sysex(tc, 30.0)
    assert sx[0] == 0xF0
    assert sx[-1] == 0xF7
    assert sx[1:5] == [0x7F, 0x7F, 0x01, 0x01]
    assert sx[6] == 2
    assert sx[7] == 3
    assert sx[8] == 4


def test_absolute_timecode_from_position() -> None:
    start = Timecode(1, 0, 0, 0)
    # 1 second later @ 30 fps → 01:00:01:00
    tc = absolute_timecode(start, 1.0, 30.0)
    assert tc == Timecode(1, 0, 1, 0)
    # 15 frames later
    tc2 = absolute_timecode(start, 15 / 30.0, 30.0)
    assert tc2 == Timecode(1, 0, 0, 15)
