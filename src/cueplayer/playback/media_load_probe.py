"""Lock-free approximate media-load counters for Audio callback correlation.

Updated from Video / mixer worker threads; read from the PortAudio callback
without taking locks (GIL makes int increments / reads safe enough for
diagnostic sampling). Never write files from the Audio callback.
"""

from __future__ import annotations

# Approximate counters — no locks (Audio callback must not block).
_play_decode_submits = 0
_va_decode_windows = 0


def note_play_decode_submit() -> None:
    global _play_decode_submits
    _play_decode_submits += 1


def note_va_decode_window() -> None:
    global _va_decode_windows
    _va_decode_windows += 1


def snapshot() -> tuple[int, int]:
    """Return (playback_decode_submits, video_audio_decode_windows)."""
    return int(_play_decode_submits), int(_va_decode_windows)


def reset() -> None:
    global _play_decode_submits, _va_decode_windows
    _play_decode_submits = 0
    _va_decode_windows = 0
