"""Windows multimedia MIDI output via winmm.dll (no pygame / rtmidi needed).

Used as the last-resort MTC backend on Windows when optional MIDI packages
are missing — Python 3.14 especially has no official ``pygame`` wheels.
"""

from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes
from typing import Any

MAXPNAMELEN = 32


class MIDIOUTCAPSW(ctypes.Structure):
    _fields_ = [
        ("wMid", wintypes.WORD),
        ("wPid", wintypes.WORD),
        ("vDriverVersion", wintypes.DWORD),
        ("szPname", wintypes.WCHAR * MAXPNAMELEN),
        ("wTechnology", wintypes.WORD),
        ("wVoices", wintypes.WORD),
        ("wNotes", wintypes.WORD),
        ("wChannelMask", wintypes.WORD),
        ("dwSupport", wintypes.DWORD),
    ]


class MIDIHDR(ctypes.Structure):
    _fields_ = [
        ("lpData", ctypes.c_void_p),
        ("dwBufferLength", wintypes.DWORD),
        ("dwBytesRecorded", wintypes.DWORD),
        ("dwUser", ctypes.c_void_p),
        ("dwFlags", wintypes.DWORD),
        ("lpNext", ctypes.c_void_p),
        ("reserved", ctypes.c_void_p),
        ("dwOffset", wintypes.DWORD),
        ("dwReserved", ctypes.c_void_p * 8),
    ]


def winmm_available() -> bool:
    return sys.platform.startswith("win")


_timer_period_set = False


def request_timer_resolution(period_ms: int = 1) -> None:
    """Ask Windows for high-resolution timer (timeBeginPeriod).

    Reduces Qt/system timer jitter from ~15ms to ~1ms during playback.
    Safe to call multiple times; tracks state to avoid double-set.
    """
    global _timer_period_set
    if not sys.platform.startswith("win") or _timer_period_set:
        return
    try:
        ctypes.windll.winmm.timeBeginPeriod(period_ms)
        _timer_period_set = True
    except Exception:  # noqa: BLE001
        pass


def release_timer_resolution(period_ms: int = 1) -> None:
    """Release high-resolution timer request (timeEndPeriod)."""
    global _timer_period_set
    if not sys.platform.startswith("win") or not _timer_period_set:
        return
    try:
        ctypes.windll.winmm.timeEndPeriod(period_ms)
        _timer_period_set = False
    except Exception:  # noqa: BLE001
        pass


def _winmm() -> Any:
    return ctypes.windll.winmm


def list_winmm_output_names() -> list[str]:
    if not winmm_available():
        return []
    midi = _winmm()
    count = int(midi.midiOutGetNumDevs())
    names: list[str] = []
    for index in range(count):
        caps = MIDIOUTCAPSW()
        result = midi.midiOutGetDevCapsW(index, ctypes.byref(caps), ctypes.sizeof(caps))
        if result == 0:
            name = str(caps.szPname).strip("\x00")
            if name:
                names.append(name)
    return names


class WinmmMidiOut:
    """Minimal MIDI output port compatible with MtcOutput's send/close usage."""

    def __init__(self, device_index: int, name: str) -> None:
        self.name = name
        self._handle = wintypes.HANDLE()
        midi = _winmm()
        result = midi.midiOutOpen(
            ctypes.byref(self._handle),
            device_index,
            0,
            0,
            0,
        )
        if result != 0:
            raise OSError(f"midiOutOpen failed ({result}) for {name!r}")
        self._closed = False

    @staticmethod
    def _norm_port_name(name: str) -> str:
        return (
            name.strip()
            .replace("\u2019", "'")
            .replace("\u2018", "'")
            .casefold()
        )

    @classmethod
    def open_by_name(cls, port_name: str) -> WinmmMidiOut:
        names = list_winmm_output_names()
        if port_name in names:
            index = names.index(port_name)
            return cls(index, port_name)
        want = cls._norm_port_name(port_name)
        for i, n in enumerate(names):
            if cls._norm_port_name(n) == want:
                return cls(i, n)
        match = next(
            (i for i, n in enumerate(names) if port_name in n or n in port_name),
            None,
        )
        if match is None:
            match = next(
                (
                    i
                    for i, n in enumerate(names)
                    if want in cls._norm_port_name(n)
                    or cls._norm_port_name(n) in want
                ),
                None,
            )
        if match is None:
            raise LookupError(f"MIDI port not found: {port_name}")
        return cls(match, names[match])

    def send(self, message: Any) -> None:
        if self._closed:
            return
        # Accept mido.Message or a duck-typed object with .type / .bytes().
        data = bytes(message.bytes()) if hasattr(message, "bytes") else bytes(message)
        if not data:
            return
        midi = _winmm()
        if data[0] == 0xF0:
            self._send_sysex(data)
            return
        if len(data) == 1:
            packed = data[0]
        elif len(data) == 2:
            packed = data[0] | (data[1] << 8)
        else:
            packed = data[0] | (data[1] << 8) | (data[2] << 16)
        result = midi.midiOutShortMsg(self._handle, packed)
        if result != 0:
            raise OSError(f"midiOutShortMsg failed ({result})")

    def _send_sysex(self, data: bytes) -> None:
        midi = _winmm()
        buf = ctypes.create_string_buffer(data)
        header = MIDIHDR()
        header.lpData = ctypes.cast(buf, ctypes.c_void_p)
        header.dwBufferLength = len(data)
        header.dwFlags = 0
        prep = midi.midiOutPrepareHeader(
            self._handle, ctypes.byref(header), ctypes.sizeof(header)
        )
        if prep != 0:
            raise OSError(f"midiOutPrepareHeader failed ({prep})")
        try:
            sent = midi.midiOutLongMsg(
                self._handle, ctypes.byref(header), ctypes.sizeof(header)
            )
            if sent != 0:
                raise OSError(f"midiOutLongMsg failed ({sent})")
        finally:
            # Wait briefly for MHDR_DONE if the driver marks it asynchronously.
            for _ in range(50):
                if header.dwFlags & 0x00000001:  # MHDR_DONE
                    break
                import time

                time.sleep(0.001)
            midi.midiOutUnprepareHeader(
                self._handle, ctypes.byref(header), ctypes.sizeof(header)
            )

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            _winmm().midiOutClose(self._handle)
        except Exception:
            pass
