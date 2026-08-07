"""Read-only grandMA2 live-pool scanner transport.

MA2's command Telnet port accepts console commands but is not a reliable
query-response API.  CuePlayer therefore triggers a read-only Lua scanner
Plugin through port 30000 and consumes its explicitly framed ``gma.echo``
output on System Monitor port 30001.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
import socket
import time


FRAME_BEGIN = "CUEPLAYER_SCAN_BEGIN"
FRAME_END = "CUEPLAYER_SCAN_END"
PLUGIN_NAME = "CuePlayer Live Scan"
POOL_KINDS = ("sequence", "effect", "timecode", "macro", "view")


class Ma2TelnetError(RuntimeError):
    """A live MA2 connection or scanner-frame error."""


@dataclass(frozen=True)
class Ma2PoolSnapshot:
    version: str
    sequence: frozenset[int]
    effect: frozenset[int]
    timecode: frozenset[int]
    macro: frozenset[int]
    view: frozenset[int]

    def next_free(self, kind: str) -> int:
        values = getattr(self, kind)
        return max(values, default=0) + 1


def parse_scan_frame(text: str) -> Ma2PoolSnapshot:
    """Parse one noisy System Monitor stream containing a CuePlayer frame."""
    begin = text.find(FRAME_BEGIN)
    end = text.find(FRAME_END, begin + len(FRAME_BEGIN))
    if begin < 0 or end < 0:
        raise Ma2TelnetError("CuePlayer scanner frame was not received")
    frame = text[begin : end + len(FRAME_END)]
    values: dict[str, frozenset[int]] = {}
    for kind in POOL_KINDS:
        match = re.search(rf"CUEPLAYER_SCAN_{kind.upper()}=([^\r\n]*)", frame)
        numbers = (
            frozenset(int(value) for value in re.findall(r"\d+", match.group(1)))
            if match
            else frozenset()
        )
        values[kind] = numbers
    version_match = re.search(r"CUEPLAYER_SCAN_VERSION=([0-9.]+)", frame)
    if not version_match:
        raise Ma2TelnetError("CuePlayer scanner did not report an MA2 version")
    return Ma2PoolSnapshot(version=version_match.group(1), **values)


class Ma2TelnetScanner:
    """Small synchronous client used by the Export Registry UI."""

    def __init__(self, host: str, *, command_port: int = 30000, monitor_port: int = 30001, timeout_seconds: float = 3.0) -> None:
        self.host = host.strip()
        self.command_port = int(command_port)
        self.monitor_port = int(monitor_port)
        self.timeout_seconds = max(0.2, float(timeout_seconds))

    def _connect(self, port: int) -> socket.socket:
        if not self.host:
            raise Ma2TelnetError("MA2 Host is required")
        try:
            return socket.create_connection((self.host, port), self.timeout_seconds)
        except OSError as exc:
            raise Ma2TelnetError(f"Could not connect to {self.host}:{port}: {exc}") from exc

    @staticmethod
    def _send_line(conn: socket.socket, command: str) -> None:
        conn.sendall((command.rstrip("\r\n") + "\r\n").encode("utf-8"))

    def _login(self, conn: socket.socket, user: str, password: str) -> None:
        """Issue MA2's required command-line Login command.

        MA2 opens a command line on port 30000 but it does not interpret raw
        username/password lines as a Telnet prompt exchange.  The console
        requires ``Login \"user\" \"password\"`` before other commands.
        """
        username = user.strip()
        if not username:
            raise Ma2TelnetError("MA2 show user is required for Command Telnet")
        safe_user = username.replace('"', "")
        safe_password = password.replace('"', "")
        # Do not log either value or persist the password.
        self._send_line(conn, f'Login "{safe_user}" "{safe_password}"')

    def test_connection(self, *, user: str = "", password: str = "") -> None:
        with self._connect(self.command_port) as command:
            self._login(command, user, password)
            self._send_line(command, 'Echo "CuePlayer connection test"')

    def import_plugin(
        self,
        *,
        plugin_pool: int,
        import_path: str,
        user: str = "",
        password: str = "",
    ) -> None:
        """Install the generated scanner Plugin at an explicitly chosen Pool ID.

        MA2's Import command overwrites an occupied destination, so callers must
        obtain an explicit user confirmation before invoking this method.
        ``import_path`` is MA2's path to the Plugin XML, not necessarily the
        local CuePlayer filesystem path when scanning a remote console.
        """
        plugin_pool = int(plugin_pool)
        if plugin_pool < 2:
            raise Ma2TelnetError("Choose an unused Plugin Pool number of 2 or higher")
        path = import_path.strip()
        if not path:
            raise Ma2TelnetError("MA2 Plugin import path is required")
        safe_path = path.replace('"', "")
        with self._connect(self.command_port) as command:
            self._login(command, user, password)
            self._send_line(
                command,
                f'Import "CuePlayer_Live_Scan" At Plugin {plugin_pool} '
                f'/path="{safe_path}" /nc',
            )

    def scan(
        self,
        *,
        user: str = "",
        password: str = "",
        plugin_pool: int | None = None,
    ) -> Ma2PoolSnapshot:
        """Run the installed read-only scanner Plugin and wait for its frame."""
        with self._connect(self.monitor_port) as monitor, self._connect(self.command_port) as command:
            self._login(command, user, password)
            command_text = (
                f"Plugin {int(plugin_pool)}"
                if plugin_pool is not None
                else f'Plugin "{PLUGIN_NAME}"'
            )
            self._send_line(command, command_text)
            deadline = time.monotonic() + self.timeout_seconds
            chunks: list[str] = []
            while time.monotonic() < deadline:
                remaining = max(0.05, deadline - time.monotonic())
                monitor.settimeout(remaining)
                try:
                    block = monitor.recv(4096)
                except TimeoutError:
                    continue
                if not block:
                    break
                chunks.append(block.decode("utf-8", errors="replace"))
                joined = "".join(chunks)
                if FRAME_BEGIN in joined and FRAME_END in joined:
                    return parse_scan_frame(joined)
        raise Ma2TelnetError(
            "No scanner response. Import and run the CuePlayer Live Scan Plugin, "
            "then make sure System Monitor port 30001 is enabled."
        )


def live_scan_plugin_lua() -> str:
    """Lua payload for the MA2 Plugin that emits only read-only Pool metadata."""
    return """-- CuePlayer Live Scan (read-only)
local function collect(kind)
  local out = {}
  for n = 1, 9999 do
    if gma.show.getobj.handle(kind .. ' ' .. n) then
      table.insert(out, tostring(n))
    end
  end
  return table.concat(out, ',')
end
local function Start()
  gma.echo('CUEPLAYER_SCAN_BEGIN')
  gma.echo('CUEPLAYER_SCAN_VERSION=' .. (gma.show.getvar('VERSION') or '0.0.0.0'))
  gma.echo('CUEPLAYER_SCAN_SEQUENCE=' .. collect('Sequence'))
  gma.echo('CUEPLAYER_SCAN_EFFECT=' .. collect('Effect'))
  gma.echo('CUEPLAYER_SCAN_TIMECODE=' .. collect('Timecode'))
  gma.echo('CUEPLAYER_SCAN_MACRO=' .. collect('Macro'))
  gma.echo('CUEPLAYER_SCAN_VIEW=' .. collect('View'))
  gma.echo('CUEPLAYER_SCAN_END')
end
return Start
"""
