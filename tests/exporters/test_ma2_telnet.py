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


def test_parse_scan_frame_merges_chunked_pool_lines() -> None:
    snapshot = parse_scan_frame(
        f"{FRAME_BEGIN}\n"
        "CUEPLAYER_SCAN_VERSION=3.9.60\n"
        "CUEPLAYER_SCAN_EFFECT=601,602\n"
        "CUEPLAYER_SCAN_EFFECT=2703\n"
        f"{FRAME_END}\n"
    )
    assert snapshot.effect == frozenset({601, 602, 2703})


def test_scan_logs_in_triggers_plugin_pool_and_reads_fragmented_monitor_frame(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    command = _Socket()
    monitor = _Socket(
        [
            b"",
            b"unrelated\r\nCUEPLAYER_SCAN_BEGIN\r\nCUEPLAYER_SCAN_VERSION=3.9.60\r\n",
            b"CUEPLAYER_SCAN_SEQUENCE=41\r\nCUEPLAYER_SCAN_EFFECT=401\r\n"
            b"CUEPLAYER_SCAN_TIMECODE=203\r\nCUEPLAYER_SCAN_MACRO=205\r\n"
            b"CUEPLAYER_SCAN_VIEW=207\r\nCUEPLAYER_SCAN_END\r\n",
        ]
    )

    def connect(address, _timeout):
        return monitor if address[1] == 30001 else command

    monkeypatch.setattr("cueplayer.exporters.ma2_telnet.socket.create_connection", connect)
    snapshot = Ma2TelnetScanner("127.0.0.1").scan(
        user="CuePlayer", password="secret", plugin_pool=5
    )

    assert snapshot.next_free("sequence") == 42
    assert snapshot.next_free("view") == 208
    assert command.sent == [
        b'Login "CuePlayer" "secret"\r\n',
        b"Plugin 5\r\n",
        b"Exit\r\n",
    ]


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
    assert command.sent == [b'Login "CuePlayer" "secret"\r\n', b"Exit\r\n"]


def test_login_requires_a_ma2_show_user(monkeypatch: pytest.MonkeyPatch) -> None:
    command = _Socket()
    monkeypatch.setattr(
        "cueplayer.exporters.ma2_telnet.socket.create_connection",
        lambda *_args: command,
    )

    with pytest.raises(Ma2TelnetError, match="show user"):
        Ma2TelnetScanner("127.0.0.1").test_connection()


def test_import_plugin_uses_explicit_pool_and_ma2_visible_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    command = _Socket()
    monkeypatch.setattr(
        "cueplayer.exporters.ma2_telnet.socket.create_connection",
        lambda *_args: command,
    )

    Ma2TelnetScanner("127.0.0.1").import_plugin(
        plugin_pool=9999,
        import_path="/data/ma/actual/gma2/plugins",
        user="CuePlayer",
        password="secret",
    )

    assert command.sent[-2] == (
        b'Import "CuePlayer_Live_Scan" At Plugin 9999 '
        b'/path="/data/ma/actual/gma2/plugins"\r\n'
    )


def test_import_plugin_rejects_reserved_plugin_one() -> None:
    with pytest.raises(Ma2TelnetError, match="2 or higher"):
        Ma2TelnetScanner("127.0.0.1").import_plugin(
            plugin_pool=1,
            import_path="/data/ma/actual/gma2/plugins",
        )


def test_local_import_matches_the_ma2_command_line_form(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    command = _Socket()
    monkeypatch.setattr(
        "cueplayer.exporters.ma2_telnet.socket.create_connection",
        lambda *_args: command,
    )

    Ma2TelnetScanner("127.0.0.1").import_plugin(
        plugin_pool=5, user="administrator", password="admin"
    )

    assert command.sent[-2] == b'Import "CuePlayer_Live_Scan" At Plugin 5\r\n'


def test_scan_can_run_the_explicitly_installed_plugin_pool(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    command = _Socket()
    monitor = _Socket(
        [
            b"",
            (
                b"CUEPLAYER_SCAN_BEGIN\r\nCUEPLAYER_SCAN_VERSION=3.9.60\r\n"
                b"CUEPLAYER_SCAN_SEQUENCE=1\r\nCUEPLAYER_SCAN_EFFECT=201\r\n"
                b"CUEPLAYER_SCAN_TIMECODE=201\r\nCUEPLAYER_SCAN_MACRO=201\r\n"
                b"CUEPLAYER_SCAN_VIEW=201\r\nCUEPLAYER_SCAN_END\r\n"
            )
        ]
    )
    monkeypatch.setattr(
        "cueplayer.exporters.ma2_telnet.socket.create_connection",
        lambda address, _timeout: monitor if address[1] == 30001 else command,
    )

    Ma2TelnetScanner("127.0.0.1").scan(user="CuePlayer", plugin_pool=9999)

    assert command.sent[-2] == b"Plugin 9999\r\n"


def test_telnet_negotiation_declines_optional_server_features(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    command = _Socket([bytes([255, 253, 1]), b""])
    monkeypatch.setattr(
        "cueplayer.exporters.ma2_telnet.socket.create_connection",
        lambda *_args: command,
    )

    Ma2TelnetScanner("127.0.0.1").test_connection(user="CuePlayer")

    assert command.sent[0] == bytes([255, 252, 1])
    assert command.sent[1] == b'Login "CuePlayer" ""\r\n'
    assert command.sent[-1] == b"Exit\r\n"


def test_connection_hides_telnet_control_bytes_from_status_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    command = _Socket([b"", bytes([255, 253, 1]) + b"MA2 ready\r\n"])
    monkeypatch.setattr(
        "cueplayer.exporters.ma2_telnet.socket.create_connection",
        lambda *_args: command,
    )

    feedback = Ma2TelnetScanner("127.0.0.1").test_connection(user="CuePlayer")

    assert feedback == "MA2 ready\r\n"
    assert bytes([255, 252, 1]) in command.sent
    assert command.sent[-1] == b"Exit\r\n"


def test_command_waits_for_ma2_login_prompt_before_writing_input(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    command = _Socket([b"\x1b[37mMA2 banner", b"\r\nPlease login !\r\n", b""])
    monkeypatch.setattr(
        "cueplayer.exporters.ma2_telnet.socket.create_connection",
        lambda *_args: command,
    )

    Ma2TelnetScanner("127.0.0.1").test_connection(user="administrator", password="admin")

    assert command.sent == [b'Login "administrator" "admin"\r\n', b"Exit\r\n"]
