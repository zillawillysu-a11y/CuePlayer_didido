"""Fire short MIDI notes when Main / Button marks are crossed during play."""

from __future__ import annotations

import logging
import threading
from typing import Any

from cueplayer.domain.models import Mark, MarkLane, Song

log = logging.getLogger(__name__)


def default_note_for_lane(
    lane: MarkLane,
    *,
    main_base: int = 36,
    button_base: int = 48,
) -> int:
    """Map lane index to a MIDI note (0–127)."""
    base = main_base if lane.lane_type == "main" else button_base
    note = int(base) + max(0, int(lane.index) - 1)
    return max(0, min(127, note))


class MidiCueNotes:
    """
    Edge-detect marks on the playback clock and send Note On/Off.

    Uses the same MIDI output port name as MTC (opened separately only when
    cue notes are enabled and MTC is not already holding a compatible port —
    prefer injecting an external send callback when available).
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._enabled = False
        self._port_name = ""
        self._port: Any = None
        self._owns_port = False
        self._channel = 0  # 0–15
        self._velocity = 100
        self._main_base = 36
        self._button_base = 48
        self._song: Song | None = None
        self._last_position = 0.0
        self._playing = False
        self._send_fn: Any = None

    def set_send_function(self, send_fn: Any) -> None:
        """Optional: reuse an already-open MIDI port (e.g. MtcOutput.send)."""
        with self._lock:
            self._send_fn = send_fn

    def configure(
        self,
        *,
        enabled: bool,
        port_name: str,
        channel: int = 1,
        velocity: int = 100,
        main_base_note: int = 36,
        button_base_note: int = 48,
    ) -> str | None:
        with self._lock:
            new_port_name = (port_name or "").strip()
            port_changed = new_port_name != self._port_name
            self._enabled = bool(enabled)
            self._port_name = new_port_name
            self._channel = max(0, min(15, int(channel) - 1))
            self._velocity = max(1, min(127, int(velocity)))
            self._main_base = max(0, min(127, int(main_base_note)))
            self._button_base = max(0, min(127, int(button_base_note)))
            if not self._enabled:
                # Keep port open for fast re-enable.
                return None
            if self._send_fn is not None:
                return None
            if self._port is not None and not port_changed:
                return None
            return self._reopen_port_locked()

    def set_song(self, song: Song | None) -> None:
        with self._lock:
            self._song = song
            self._last_position = 0.0

    def on_play(self, position_seconds: float) -> None:
        with self._lock:
            self._playing = True
            self._last_position = max(0.0, float(position_seconds))

    def on_pause(self) -> None:
        with self._lock:
            self._playing = False

    def on_seek(self, position_seconds: float) -> None:
        with self._lock:
            self._last_position = max(0.0, float(position_seconds))

    def update(self, position_seconds: float) -> None:
        """Call from the engine position timer while playing."""
        with self._lock:
            if not self._enabled or not self._playing or self._song is None:
                self._last_position = max(0.0, float(position_seconds))
                return
            pos = max(0.0, float(position_seconds))
            prev = self._last_position
            self._last_position = pos
            if pos <= prev:
                return
            marks = self._marks_to_fire_locked(prev, pos)
            for mark, lane in marks:
                self._send_note_locked(lane, mark)

    def close(self) -> None:
        with self._lock:
            self._enabled = False
            self._playing = False
            self._close_port_locked()

    def _marks_to_fire_locked(
        self, prev: float, pos: float
    ) -> list[tuple[Mark, MarkLane]]:
        song = self._song
        if song is None:
            return []
        fired: list[tuple[Mark, MarkLane]] = []
        for mark in song.marks:
            if not (prev < float(mark.time_seconds) <= pos):
                continue
            lane = song.lane_by_index(mark.lane_index)
            if lane is None:
                continue
            if not bool(getattr(lane, "midi_note_enabled", False)):
                continue
            fired.append((mark, lane))
        fired.sort(key=lambda pair: float(pair[0].time_seconds))
        return fired

    def _note_for_lane_locked(self, lane: MarkLane) -> int:
        custom = int(getattr(lane, "midi_note", 0) or 0)
        if 1 <= custom <= 127:
            return custom
        return default_note_for_lane(
            lane, main_base=self._main_base, button_base=self._button_base
        )

    def _send_note_locked(self, lane: MarkLane, mark: Mark) -> None:
        del mark  # reserved for future note naming / logging
        note = self._note_for_lane_locked(lane)
        status_on = 0x90 | self._channel
        status_off = 0x80 | self._channel
        vel = self._velocity
        try:
            self._emit_locked(status_on, note, vel)
            self._emit_locked(status_off, note, 0)
        except Exception as exc:  # noqa: BLE001
            log.debug("MIDI cue note failed: %s", exc)

    def _emit_locked(self, status: int, note: int, velocity: int) -> None:
        class _Msg:
            def __init__(self, data: bytes) -> None:
                self._data = data

            def bytes(self) -> bytes:
                return self._data

        msg = _Msg(bytes((status & 0xFF, note & 0x7F, velocity & 0x7F)))
        if self._send_fn is not None:
            self._send_fn(msg)
            return
        if self._port is None:
            return
        self._port.send(msg)

    def _reopen_port_locked(self) -> str | None:
        self._close_port_locked()
        if not self._port_name:
            return "MIDI cue notes enabled but no MIDI output port is selected."
        from cueplayer.playback.mtc_output import list_midi_output_names
        from cueplayer.playback import mtc_output as mtc_mod

        if mtc_mod._use_winmm():  # noqa: SLF001
            import time
            for attempt in range(5):
                try:
                    from cueplayer.playback.winmm_midi import WinmmMidiOut
                    self._port = WinmmMidiOut.open_by_name(self._port_name)
                    self._owns_port = True
                    return None
                except Exception as exc:  # noqa: BLE001
                    log.warning("winmm MIDI cue open attempt %d: %s", attempt + 1, exc)
                    time.sleep(0.1)
            names = list_midi_output_names()
            hint = f" Available: {', '.join(names[:6])}" if names else ""
            return f"MIDI port not found: {self._port_name}.{hint}"
        try:
            import mido
            mtc_mod._ensure_mido_backend()  # noqa: SLF001
            self._port = mido.open_output(self._port_name)
            self._owns_port = True
            return None
        except Exception as exc:  # noqa: BLE001
            names = list_midi_output_names()
            hint = f" Available: {', '.join(names[:6])}" if names else ""
            return f"Could not open MIDI port '{self._port_name}': {exc}.{hint}"

    def _close_port_locked(self) -> None:
        port = self._port
        self._port = None
        if not self._owns_port or port is None:
            self._owns_port = False
            return
        self._owns_port = False
        try:
            port.close()
        except Exception:  # noqa: BLE001
            pass
