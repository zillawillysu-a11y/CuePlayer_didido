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
POOL_KINDS = ("sequence", "effect", "timecode", "macro", "view", "group")
_IAC = 255
_DO = 253
_DONT = 254
_WILL = 251
_WONT = 252


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
    group: frozenset[int] = frozenset()

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
        matches = re.finditer(rf"CUEPLAYER_SCAN_{kind.upper()}=([^\r\n]*)", frame)
        numbers = frozenset(
            int(value)
            for match in matches
            for value in re.findall(r"\d+", match.group(1))
        )
        values[kind] = numbers
    version_match = re.search(r"CUEPLAYER_SCAN_VERSION=([0-9.]+)", frame)
    if not version_match:
        raise Ma2TelnetError("CuePlayer scanner did not report an MA2 version")
    return Ma2PoolSnapshot(version=version_match.group(1), **values)


class Ma2TelnetScanner:
    """Small synchronous client used by the Export Registry UI."""

    def __init__(self, host: str, *, command_port: int = 30000, monitor_port: int = 30001, timeout_seconds: float = 15.0) -> None:
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

    def _negotiate_telnet(self, conn: socket.socket, *, wait_for_login_prompt: bool) -> None:
        """Drain MA2's initial ANSI screen before writing Command Telnet input."""
        deadline = time.monotonic() + min(
            0.9 if wait_for_login_prompt else 0.12,
            self.timeout_seconds,
        )
        received_text: list[str] = []
        while time.monotonic() < deadline:
            conn.settimeout(max(0.03, deadline - time.monotonic()))
            try:
                greeting = conn.recv(4096)
            except TimeoutError:
                return
            if not greeting:
                return
            received_text.append(self._telnet_text(conn, greeting))
            if wait_for_login_prompt and "Please login" in "".join(received_text):
                return

    @staticmethod
    def _telnet_text(conn: socket.socket, data: bytes) -> str:
        """Reply to Telnet control bytes and return only displayable text."""
        response = bytearray()
        text = bytearray()
        index = 0
        while index < len(data):
            if data[index] != _IAC:
                text.append(data[index])
                index += 1
                continue
            if index + 1 >= len(data):
                break
            command = data[index + 1]
            if command in (_DO, _DONT, _WILL, _WONT):
                if index + 2 >= len(data):
                    break
                option = data[index + 2]
                reply = _WONT if command in (_DO, _DONT) else _DONT
                response.extend((_IAC, reply, option))
                index += 3
            elif command == _IAC:
                text.append(_IAC)
                index += 2
            else:
                index += 2
        if response:
            conn.sendall(bytes(response))
        return text.decode("utf-8", errors="replace")

    def _read_feedback(self, conn: socket.socket, *, wait_seconds: float = 0.5) -> str:
        """Read post-command feedback while allowing MA2 to finish the command."""
        deadline = time.monotonic() + max(0.05, wait_seconds)
        chunks: list[str] = []
        while time.monotonic() < deadline:
            try:
                conn.settimeout(min(0.5, max(0.05, deadline - time.monotonic())))
                data = conn.recv(4096)
            except TimeoutError:
                continue
            if not data:
                break
            chunks.append(self._telnet_text(conn, data))
        return "".join(chunks)

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
        # MA2 needs a short command-line turn after Login before it accepts the
        # next command.  Sending Plugin/Import immediately can make MA2 log a
        # TCP client's ``Send`` exception and close the session.
        time.sleep(0.25)

    def _exit_command_telnet(self, conn: socket.socket) -> None:
        """Close an MA2 Command Telnet session with its documented Exit command."""
        try:
            self._send_line(conn, "Exit")
            self._read_feedback(conn, wait_seconds=0.25)
        except OSError:
            # The station may close immediately after accepting Exit.
            pass

    def test_connection(self, *, user: str = "", password: str = "") -> str:
        with self._connect(self.command_port) as command:
            self._negotiate_telnet(command, wait_for_login_prompt=True)
            self._login(command, user, password)
            # Login is the connectivity test.  MA2's Command Line does not
            # provide a portable no-op Echo command; sending one only creates
            # a misleading ``Error: Echo`` in Command Line Feedback.
            feedback = self._read_feedback(command)
            self._exit_command_telnet(command)
            return feedback

    def import_plugin(
        self,
        *,
        plugin_pool: int,
        import_path: str = "",
        user: str = "",
        password: str = "",
    ) -> str:
        """Install the generated scanner Plugin at an explicitly chosen Pool ID.

        MA2's Import command overwrites an occupied destination, so callers must
        obtain an explicit user confirmation before invoking this method.
        A custom ``import_path`` is only needed when the MA2 console cannot
        already locate the Plugin file on its selected drive.
        """
        plugin_pool = int(plugin_pool)
        if plugin_pool < 2:
            raise Ma2TelnetError("Choose an unused Plugin Pool number of 2 or higher")
        path = import_path.strip()
        safe_path = path.replace('"', "")
        with self._connect(self.command_port) as command:
            self._negotiate_telnet(command, wait_for_login_prompt=True)
            self._login(command, user, password)
            import_command = f'Import "CuePlayer_Live_Scan" At Plugin {plugin_pool}'
            if safe_path:
                import_command += f' /path="{safe_path}"'
            self._send_line(command, import_command)
            # Import can take longer than the command socket's first response;
            # keep it open so MA2 does not report a Send exception mid-import.
            feedback = self._read_feedback(command, wait_seconds=1.5)
            self._exit_command_telnet(command)
            return feedback

    def scan(
        self,
        *,
        user: str = "",
        password: str = "",
        plugin_pool: int,
    ) -> Ma2PoolSnapshot:
        """Run the installed scanner Plugin Pool and wait for its frame."""
        plugin_pool = int(plugin_pool)
        if plugin_pool < 2:
            raise Ma2TelnetError("Choose a scanner Plugin Pool number of 2 or higher")
        with self._connect(self.monitor_port) as monitor, self._connect(self.command_port) as command:
            self._negotiate_telnet(monitor, wait_for_login_prompt=False)
            self._negotiate_telnet(command, wait_for_login_prompt=True)
            self._login(command, user, password)
            self._send_line(command, f"Plugin {plugin_pool}")
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
                chunks.append(self._telnet_text(monitor, block))
                joined = "".join(chunks)
                if FRAME_BEGIN in joined and FRAME_END in joined:
                    snapshot = parse_scan_frame(joined)
                    self._exit_command_telnet(command)
                    return snapshot
            self._exit_command_telnet(command)
        received = "".join(chunks)
        if received.strip():
            raise Ma2TelnetError(
                "MA2 connected, but the scanner frame was not received within "
                f"{self.timeout_seconds:g}s. The Plugin may still be scanning; "
                "try Scan again after confirming it is installed and ran successfully."
            )
        raise Ma2TelnetError(
            "MA2 connected, but System Monitor 30001 returned no scanner output. "
            "Import and run the CuePlayer Live Scan Plugin, then make sure System Monitor port 30001 is enabled."
        )


def live_scan_plugin_lua() -> str:
    """Lua payload for the MA2 Plugin that emits only read-only Pool metadata."""
    return """-- CuePlayer Live Scan (read-only)
local function emit(kind)
  local out = {}
  local chunk = {}
  for n = 1, 9999 do
    if gma.show.getobj.handle(kind .. ' ' .. n) then
      table.insert(chunk, tostring(n))
      if #chunk >= 100 then
        table.insert(out, table.concat(chunk, ','))
        chunk = {}
      end
    end
  end
  if #chunk > 0 then table.insert(out, table.concat(chunk, ',')) end
  for _, part in ipairs(out) do
    gma.echo('CUEPLAYER_SCAN_' .. string.upper(kind) .. '=' .. part)
  end
end
local function Start()
  gma.echo('CUEPLAYER_SCAN_BEGIN')
  gma.echo('CUEPLAYER_SCAN_VERSION=' .. (gma.show.getvar('VERSION') or '0.0.0.0'))
  emit('Sequence')
  emit('Effect')
  emit('Timecode')
  emit('Macro')
  emit('View')
  emit('Group')
  gma.echo('CUEPLAYER_SCAN_END')
end
return Start
"""
