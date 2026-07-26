"""MIDI Timecode (MTC) quarter-frame and full-frame helpers."""

from __future__ import annotations

from cueplayer.timecode.smpte import Timecode, _frame_rate


def mtc_rate_code(fps: float) -> int:
    """
    Rate bits packed into quarter-frame message type 7 / full-frame hour byte.

    0 = 24, 1 = 25, 2 = 29.97 drop, 3 = 30 (and 29.97 NDF treated as 30).
    """
    if abs(fps - 24.0) < 0.15:
        return 0
    if abs(fps - 25.0) < 0.15:
        return 1
    if abs(fps - 29.97) < 0.05:
        # Drop-frame not implemented yet; advertise 30 fps NDF.
        return 3
    return 3


def quarter_frame_payload(tc: Timecode, message_type: int, fps: float) -> int:
    """
    Return the single data byte for MTC quarter-frame message type 0–7.

    MIDI message is status 0xF1 + this byte: ``(type << 4) | nibble``.
    """
    mt = int(message_type) & 0x07
    rate = mtc_rate_code(fps)
    if mt == 0:
        nibble = tc.frames & 0x0F
    elif mt == 1:
        nibble = (tc.frames >> 4) & 0x0F
    elif mt == 2:
        nibble = tc.seconds & 0x0F
    elif mt == 3:
        nibble = (tc.seconds >> 4) & 0x0F
    elif mt == 4:
        nibble = tc.minutes & 0x0F
    elif mt == 5:
        nibble = (tc.minutes >> 4) & 0x0F
    elif mt == 6:
        nibble = tc.hours & 0x0F
    else:
        nibble = ((tc.hours >> 4) & 0x01) | ((rate & 0x03) << 1)
    return ((mt & 0x07) << 4) | (nibble & 0x0F)


def quarter_frame_messages(tc: Timecode, fps: float) -> list[tuple[int, int]]:
    """Eight (status, data) pairs encoding ``tc`` as MTC quarter frames."""
    return [(0xF1, quarter_frame_payload(tc, i, fps)) for i in range(8)]


def full_frame_sysex(tc: Timecode, fps: float) -> list[int]:
    """
    MIDI full-frame dump SysEx (nice-to-have on seek / play start).

    F0 7F 7F 01 01 hr mn sc fr F7
    """
    rate = mtc_rate_code(fps)
    hr = (tc.hours & 0x1F) | ((rate & 0x03) << 5)
    return [
        0xF0,
        0x7F,
        0x7F,
        0x01,
        0x01,
        hr,
        tc.minutes & 0x7F,
        tc.seconds & 0x7F,
        tc.frames & 0x7F,
        0xF7,
    ]


def absolute_timecode(start: Timecode, position_seconds: float, fps: float) -> Timecode:
    """Song-relative position → absolute SMPTE at song fps."""
    rate = _frame_rate(fps)
    real_fps = fps if fps > 0 else 30.0
    start_frames = start.total_frames(fps)
    delta = int(round(max(0.0, position_seconds) * real_fps))
    total = start_frames + delta
    frames = total % rate
    total //= rate
    secs = total % 60
    total //= 60
    mins = total % 60
    hours = (total // 60) % 24
    return Timecode(hours, mins, secs, frames)
