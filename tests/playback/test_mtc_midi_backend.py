"""MIDI / MTC backend helpers (winmm on Windows, optional pygame-ce elsewhere)."""

from __future__ import annotations

import sys

from cueplayer.playback.mtc_output import (
    list_midi_output_names,
    midi_backend_status,
    MtcOutput,
)
from cueplayer.playback.winmm_midi import list_winmm_output_names, winmm_available


def test_winmm_available_matches_platform() -> None:
    assert winmm_available() is sys.platform.startswith("win")


def test_list_winmm_names_empty_off_windows() -> None:
    if not sys.platform.startswith("win"):
        assert list_winmm_output_names() == []


def test_midi_backend_status_is_nonempty() -> None:
    status = midi_backend_status()
    assert isinstance(status, str)
    assert status.strip()
    if sys.platform.startswith("win"):
        assert "winmm" in status.lower()
    else:
        # Without rtmidi/pygame on CI Linux, expect install guidance or a named backend.
        assert "midi" in status.lower() or "pygame" in status.lower() or "mido" in status.lower()


def test_list_midi_output_names_returns_list() -> None:
    names = list_midi_output_names()
    assert isinstance(names, list)
    assert all(isinstance(n, str) for n in names)


def test_mtc_configure_missing_port_reports_error() -> None:
    out = MtcOutput()
    try:
        err = out.configure(
            enabled=True,
            port_name="",
            start_timecode="01:00:00:00",
            fps=30.0,
        )
        assert err is not None
        assert "no MIDI output port" in err
    finally:
        out.close()


def test_mtc_configure_unknown_port_reports_error() -> None:
    out = MtcOutput()
    try:
        err = out.configure(
            enabled=True,
            port_name="__cueplayer_no_such_midi_port__",
            start_timecode="01:00:00:00",
            fps=30.0,
        )
        # Either port-not-found or no-backend — never silent success.
        assert err is not None
    finally:
        out.close()
