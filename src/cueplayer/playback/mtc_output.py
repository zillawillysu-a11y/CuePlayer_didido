"""MIDI Timecode output driven by the playback sample clock."""

from __future__ import annotations

import logging
import sys
import threading
from typing import Any

from cueplayer.timecode.mtc import (
    absolute_timecode,
    full_frame_sysex,
    quarter_frame_payload,
)
from cueplayer.timecode.smpte import Timecode, add_frames, parse_timecode

log = logging.getLogger(__name__)

_BACKEND_READY = False
_BACKEND_KIND = ""  # "winmm" | "rtmidi" | "pygame" | ""


def _use_winmm() -> bool:
    if not sys.platform.startswith("win"):
        return False
    from cueplayer.playback.winmm_midi import winmm_available

    return winmm_available()


def _ensure_mido_backend() -> None:
    """Prefer rtmidi; fall back to pygame / pygame-ce (no compiler on Windows)."""
    global _BACKEND_READY, _BACKEND_KIND
    if _BACKEND_READY and _BACKEND_KIND in {"rtmidi", "pygame"}:
        return
    import os

    os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
    import mido

    try:
        import rtmidi  # noqa: F401

        _BACKEND_READY = True
        _BACKEND_KIND = "rtmidi"
        return
    except ImportError:
        pass
    try:
        import pygame  # noqa: F401

        mido.set_backend("mido.backends.pygame")
        _BACKEND_READY = True
        _BACKEND_KIND = "pygame"
        return
    except Exception as exc:  # noqa: BLE001
        log.warning(
            "mido MIDI backend unavailable (%s). "
            "On Windows CuePlayer uses winmm.dll without pygame. "
            "Otherwise install: pip install pygame-ce",
            exc,
        )


def midi_backend_status() -> str:
    """Human-readable MIDI backend readiness for UI status / dialogs."""
    if _use_winmm():
        from cueplayer.playback.winmm_midi import list_winmm_output_names

        n = len(list_winmm_output_names())
        return f"MIDI backend: Windows winmm ({n} output{'s' if n != 1 else ''})"
    try:
        import mido  # noqa: F401
    except ImportError:
        return "mido is not installed"
    _ensure_mido_backend()
    if not _BACKEND_READY:
        return (
            "No MIDI backend. On Python 3.14 use pygame-ce (not pygame):\n"
            "  .\\.venv\\Scripts\\python.exe -m pip install pygame-ce\n"
            "Or: pip install -e \".[midi]\""
        )
    if _BACKEND_KIND == "rtmidi":
        return "MIDI backend: python-rtmidi"
    if _BACKEND_KIND == "pygame":
        return "MIDI backend: pygame / pygame-ce"
    return "MIDI backend: ready"


def list_midi_output_names() -> list[str]:
    """Return available MIDI output port names (empty if no backend)."""
    if _use_winmm():
        from cueplayer.playback.winmm_midi import list_winmm_output_names

        try:
            return list_winmm_output_names()
        except Exception as exc:  # noqa: BLE001
            log.warning("Could not list winmm MIDI outputs: %s", exc)
            # Fall through to mido backends.
    try:
        import mido
    except ImportError:
        return []
    _ensure_mido_backend()
    if not _BACKEND_READY:
        return []
    try:
        return list(mido.get_output_names())
    except Exception as exc:  # noqa: BLE001
        log.warning("Could not list MIDI outputs: %s", exc)
        return []


class MtcOutput:
    """
    Sends MTC quarter frames while playing; optional full-frame dump on seek/play.

    Call ``tick(position_seconds)`` from the UI/audio poll (~4–16 ms). Uses the
    playback position (not wall clock) so MTC stays locked to the audio engine.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._enabled = False
        self._port_name = ""
        self._port: Any = None
        self._start_tc = Timecode(1, 0, 0, 0)
        self._fps = 30.0
        self._playing = False
        self._last_qf_index = -1
        self._qf_piece = 0  # 0–7 cycling

    @property
    def enabled(self) -> bool:
        with self._lock:
            return self._enabled

    @property
    def port_name(self) -> str:
        with self._lock:
            return self._port_name

    def configure(
        self,
        *,
        enabled: bool,
        port_name: str,
        start_timecode: str,
        fps: float,
    ) -> str | None:
        """
        Apply settings. Returns an error message if the port cannot be opened
        while enabled; otherwise None.
        """
        with self._lock:
            self._enabled = bool(enabled)
            self._port_name = (port_name or "").strip()
            self._fps = float(fps) if fps > 0 else 30.0
            parsed = parse_timecode(start_timecode)
            if parsed is not None:
                self._start_tc = parsed
            err = self._reopen_port_locked()
            return err

    def set_timebase(self, start_timecode: str, fps: float) -> None:
        with self._lock:
            self._fps = float(fps) if fps > 0 else 30.0
            parsed = parse_timecode(start_timecode)
            if parsed is not None:
                self._start_tc = parsed

    def set_mirror_origin(self, absolute: Timecode, position_seconds: float) -> None:
        """
        Align MTC so ``absolute`` is the timecode at ``position_seconds``.

        Used when mirroring decoded file LTC: MTC numbers match the LTC stripe
        even if Song Start TC differs.
        """
        with self._lock:
            delta = -int(round(max(0.0, float(position_seconds)) * self._fps))
            self._start_tc = add_frames(absolute, delta, self._fps)

    def on_play(self, position_seconds: float) -> None:
        with self._lock:
            if not self._enabled or self._port is None:
                self._playing = bool(self._enabled)
                return
            self._playing = True
            self._reset_qf_locked(position_seconds)
            self._send_full_frame_locked(position_seconds)

    def on_seek(self, position_seconds: float, *, playing: bool) -> None:
        with self._lock:
            if not self._enabled or self._port is None:
                return
            self._reset_qf_locked(position_seconds)
            if playing:
                self._send_full_frame_locked(position_seconds)

    def on_pause(self) -> None:
        with self._lock:
            self._playing = False

    def send_message(self, message: Any) -> None:
        """Send an arbitrary short MIDI message on the open MTC port (shared with cue notes)."""
        with self._lock:
            if self._port is None:
                return
            try:
                self._port.send(message)
            except Exception as exc:  # noqa: BLE001
                log.debug("MIDI send_message failed: %s", exc)

    def tick(self, position_seconds: float) -> None:
        """Send any quarter frames due for the current sample-clock position."""
        with self._lock:
            if not self._playing or not self._enabled or self._port is None:
                return
            fps = self._fps
            # 8 quarter frames span 2 timecode frames → 4 QF per TC frame.
            qf_rate = fps * 4.0
            if qf_rate <= 0:
                return
            target = int(max(0.0, position_seconds) * qf_rate)
            while self._last_qf_index < target:
                self._last_qf_index += 1
                # Align piece to absolute QF index so seekers stay consistent.
                piece = self._last_qf_index % 8
                # 8 QFs span 2 TC frames; freeze TC at the even frame of the group.
                group = self._last_qf_index // 8
                frame_pos = (group * 2) / fps
                tc = absolute_timecode(self._start_tc, frame_pos, fps)
                data = quarter_frame_payload(tc, piece, fps)
                try:
                    self._port.send(self._note_msg(0xF1, data))
                except Exception as exc:  # noqa: BLE001
                    log.debug("MTC send failed: %s", exc)
                    break
                self._qf_piece = (piece + 1) % 8

    def close(self) -> None:
        with self._lock:
            self._enabled = False
            self._playing = False
            self._close_port_locked()

    def _reset_qf_locked(self, position_seconds: float) -> None:
        qf_rate = self._fps * 4.0
        self._last_qf_index = int(max(0.0, position_seconds) * qf_rate) - 1
        self._qf_piece = 0

    def _send_full_frame_locked(self, position_seconds: float) -> None:
        if self._port is None:
            return
        tc = absolute_timecode(self._start_tc, position_seconds, self._fps)
        try:
            import mido

            payload = full_frame_sysex(tc, self._fps)
            # mido sysex data is bytes between F0 and F7.
            msg = mido.Message("sysex", data=payload[1:-1])
            self._port.send(msg)
        except Exception as exc:  # noqa: BLE001
            log.debug("MTC full-frame failed: %s", exc)

    def _reopen_port_locked(self) -> str | None:
        self._close_port_locked()
        if not self._enabled:
            return None
        if not self._port_name:
            return "MTC is enabled but no MIDI output port is selected."

        if _use_winmm():
            try:
                from cueplayer.playback.winmm_midi import WinmmMidiOut

                self._port = WinmmMidiOut.open_by_name(self._port_name)
                self._port_name = self._port.name
                return None
            except LookupError:
                return f"MIDI port not found: {self._port_name}"
            except Exception as exc:  # noqa: BLE001
                log.warning("winmm MIDI open failed, trying mido: %s", exc)

        try:
            import mido
        except ImportError:
            return "MTC requires the mido package."
        _ensure_mido_backend()
        if not _BACKEND_READY:
            return (
                "No MIDI backend available. "
                "On Windows, winmm should work without extra packages; "
                "otherwise install pygame-ce: pip install pygame-ce"
            )
        try:
            names = list(mido.get_output_names())
            if self._port_name not in names:
                # Allow substring match for persistence across renames.
                match = next((n for n in names if self._port_name in n), None)
                if match is None:
                    return f"MIDI port not found: {self._port_name}"
                self._port_name = match
            self._port = mido.open_output(self._port_name)
        except Exception as exc:  # noqa: BLE001
            self._port = None
            return f"Could not open MIDI port: {exc}"
        return None

    def _close_port_locked(self) -> None:
        if self._port is not None:
            try:
                self._port.close()
            except Exception:
                pass
            self._port = None

    @staticmethod
    def _note_msg(status: int, data: int) -> Any:
        import mido

        # data byte = (type << 4) | nibble
        frame_type = (data >> 4) & 0x07
        frame_value = data & 0x0F
        return mido.Message("quarter_frame", frame_type=frame_type, frame_value=frame_value)
