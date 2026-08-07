"""MA2 Telnet scanner framing and transport tests."""

from __future__ import annotations

import pytest

from cueplayer.exporters.ma2_telnet import (
    FRAME_BEGIN,
    FRAME_END,
    Ma2TelnetError,
    Ma2TelnetScanner,
    parse_scan_frame,
)


class _Socket:
    def __init__(self, chunks: list[bytes] | None = None) -> None:
        self.chunks = list(chunks or [])
        self.sent: list[bytes] = []

    def __enter__(self):
        return self

    def __exit__(self, *_args) -> None:
        return None

    def sendall(self, data: bytes) -> None:
        self.sent.append(data)

    def settimeout(self, _seconds: float) -> None:
        return None

    def recv(self, _size: int) -> bytes:
        return self.chunks.pop(0) if self.chunks else b""


def test_parse_scan_frame_ignores_monitor_noise() -> None:
    snapshot = parse_scan_frame(
        "noise\r\n"
        f"{FRAME_BEGIN}\r\n"
        "CUEPLAYER_SCAN_VERSION=3.9.63.6\r\n"
        "CUEPLAYER_SCAN_SEQUENCE=1,20,21\r\n"
        "CUEPLAYER_SCAN_EFFECT=201,202\r\n"
        "CUEPLAYER_SCAN_TIMECODE=201\r\n"
        "CUEPLAYER_SCAN_MACRO=101,201\r\n"
        "CUEPLAYER_SCAN_VIEW=201,202\r\n"
        f"{FRAME_END}\r\nnoise"
    )
    assert snapshot.version == "3.9.63.6"
    assert snapshot.sequence == frozenset({1, 20, 21})
    assert snapshot.next_free("sequence") == 22
    assert snapshot.next_free("effect") == 203


def test_scan_logs_in_triggers_plugin_and_reads_fragmented_monitor_frame(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    command = _Socket()
    monitor = _Socket(
        [
            b"unrelated\r\nCUEPLAYER_SCAN_BEGIN\r\nCUEPLAYER_SCAN_VERSION=3.9.60\r\n",
            b"CUEPLAYER_SCAN_SEQUENCE=41\r\nCUEPLAYER_SCAN_EFFECT=401\r\n"
            b"CUEPLAYER_SCAN_TIMECODE=203\r\nCUEPLAYER_SCAN_MACRO=205\r\n"
            b"CUEPLAYER_SCAN_VIEW=207\r\nCUEPLAYER_SCAN_END\r\n",
        ]
    )

    def connect(address, _timeout):
        return monitor if address[1] == 30001 else command

    monkeypatch.setattr("cueplayer.exporters.ma2_telnet.socket.create_connection", connect)
    snapshot = Ma2TelnetScanner("127.0.0.1").scan(user="CuePlayer", password="secret")

    assert snapshot.next_free("sequence") == 42
    assert snapshot.next_free("view") == 208
    assert command.sent == [b"CuePlayer\r\n", b"secret\r\n", b'Plugin "CuePlayer Live Scan"\r\n']


def test_scan_rejects_missing_frame() -> None:
    with pytest.raises(Ma2TelnetError, match="frame"):
        parse_scan_frame("ordinary monitor output")


def test_test_connection_sends_login_and_read_only_echo(monkeypatch: pytest.MonkeyPatch) -> None:
    command = _Socket()
    monkeypatch.setattr(
        "cueplayer.exporters.ma2_telnet.socket.create_connection",
        lambda *_args: command,
    )
    Ma2TelnetScanner("127.0.0.1").test_connection(user="CuePlayer", password="secret")
    assert command.sent[-1] == b'Echo "CuePlayer connection test"\r\n'
