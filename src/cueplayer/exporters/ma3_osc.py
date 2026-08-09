"""grandMA3 read-only Pool scan over OSC.

CuePlayer sends command-line OSC to run a LuaFile.  The Lua scanner reads
the selected DataPool and returns compact Pool maxima over MA3's configured
OSC output line.  No show objects are stored, changed, or deleted.
"""

from __future__ import annotations

import socket
import time
import uuid
from dataclasses import dataclass
from pathlib import Path


SCAN_ADDRESS = "/cueplayer/live_scan"
DONE_ADDRESS = "/cueplayer/live_scan/done"
ACK_ADDRESS = "/cueplayer/live_scan/ack"
LUA_FILENAME = "CuePlayer_MA3_Live_Scan.lua"


class Ma3OscError(RuntimeError):
    pass


@dataclass(frozen=True)
class Ma3PoolSnapshot:
    maxima: dict[str, int]
    scan_id: str


def _osc_string(value: str) -> bytes:
    raw = value.encode("utf-8") + b"\0"
    return raw + (b"\0" * ((-len(raw)) % 4))


def encode_osc_string(address: str, value: str) -> bytes:
    if not address.startswith("/"):
        raise ValueError("OSC address must start with /")
    return _osc_string(address) + _osc_string(",s") + _osc_string(value)


def decode_osc_string(packet: bytes) -> tuple[str, str]:
    def take(offset: int) -> tuple[str, int]:
        end = packet.index(b"\0", offset)
        value = packet[offset:end].decode("utf-8")
        return value, (end + 4) & ~3

    try:
        address, offset = take(0)
        tags, offset = take(offset)
        value, _ = take(offset)
    except (ValueError, UnicodeDecodeError) as exc:
        raise Ma3OscError("Invalid OSC packet") from exc
    if tags != ",s":
        raise Ma3OscError(f"Unsupported OSC type tag: {tags}")
    return address, value


def live_scan_lua(*, osc_output_line: int = 1) -> str:
    line = max(1, int(osc_output_line))
    return f'''-- CuePlayer grandMA3 Live Scan (read-only LuaFile)
  local scan = tostring(GetVar(GlobalVars(), "cueplayer_scan_id") or "unknown")
  local function send(address, value)
    Cmd('SendOSC {line} "' .. address .. ',s,' .. value .. '"')
  end
  local function maximum(children)
    local result = 0
    if children == nil then return result end
    for _, object in ipairs(children) do
      local address = tostring(object:Addr() or "")
      local number = tonumber(string.match(address, "(%d+)$")) or 0
      if number > result then result = number end
    end
    return result
  end
  local pool = DataPool()
  local scans = {{
    sequence = pool.Sequences,
    group = pool.Groups,
    macro = pool.Macros,
    timecode = pool.Timecodes,
    page = pool.Pages,
  }}
  for name, collection in pairs(scans) do
    send("{SCAN_ADDRESS}", scan .. "|" .. name .. "|" .. maximum(collection:Children()))
  end
  -- PresetPoolType 24 is MA3's All 5 pool.  "Preset 5" addresses the fifth
  -- feature-group preset pool instead, so it does not see the Song EFX shown
  -- by the exported View widget.
  local preset24 = pool.PresetPools and pool.PresetPools[24]
  local song_efx_max = maximum(preset24 and preset24:Children() or nil)
  local addressed_max = maximum(ObjectList("Preset 24.1 Thru 24.9999"))
  if addressed_max > song_efx_max then song_efx_max = addressed_max end
  send("{SCAN_ADDRESS}", scan .. "|effect|" .. song_efx_max)
  send("{SCAN_ADDRESS}", scan .. "|generator|" .. maximum(ObjectList("Generator 1 Thru 9999")))
  local views = ObjectList("View 1 Thru 9999")
  send("{SCAN_ADDRESS}", scan .. "|view|" .. maximum(views))
  send("{DONE_ADDRESS}", scan)
'''


def write_live_scan_lua(directory: Path, *, osc_output_line: int = 1) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / LUA_FILENAME
    path.write_text(live_scan_lua(osc_output_line=osc_output_line), encoding="utf-8")
    return path


def resolve_ma3_scan_lua_dir(export_root: Path) -> Path:
    """Resolve any supported MA3 export location to datapools/plugins."""
    root = Path(export_root)
    name = root.name.lower()
    if name == "plugins" and root.parent.name.lower() == "datapools":
        return root
    if name == "datapools":
        return root / "plugins"
    if name in {"sequences", "timecodes", "macros"} and root.parent.name.lower() == "datapools":
        return root.parent / "plugins"
    return root / "datapools" / "plugins"


class Ma3OscScanner:
    def __init__(self, host: str, *, send_port: int = 8000, listen_port: int = 8000,
                 timeout: float = 4.0) -> None:
        self.host = host.strip()
        self.send_port = int(send_port)
        self.listen_port = int(listen_port)
        self.timeout = float(timeout)
        if not self.host:
            raise Ma3OscError("MA3 Host is required")

    def _send_command(self, command: str) -> None:
        packet = encode_osc_string("/cmd", command)
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sender:
            sender.sendto(packet, (self.host, self.send_port))

    def test_connection(self, *, osc_output_line: int = 1) -> None:
        nonce = uuid.uuid4().hex[:12]
        line = max(1, int(osc_output_line))
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as receiver:
            receiver.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            receiver.bind(("", self.listen_port))
            receiver.settimeout(0.25)
            self._send_command(f'SendOSC {line} "{ACK_ADDRESS},s,{nonce}"')
            deadline = time.monotonic() + self.timeout
            while time.monotonic() < deadline:
                try:
                    packet, _peer = receiver.recvfrom(65535)
                except TimeoutError:
                    continue
                address, value = decode_osc_string(packet)
                if address == ACK_ADDRESS and value == nonce:
                    return
        raise Ma3OscError(
            "No MA3 OSC reply. Check Receive Command, output destination, and both ports."
        )

    def detect_output_line(self, *, first: int = 1, last: int = 8) -> int:
        """Return the first configured MA3 OSC output line that replies."""
        nonce = uuid.uuid4().hex[:12]
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as receiver:
            receiver.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            receiver.bind(("", self.listen_port))
            receiver.settimeout(0.25)
            for line in range(max(1, first), max(first, last) + 1):
                self._send_command(
                    f'SendOSC {line} "{ACK_ADDRESS},s,{nonce}|{line}"'
                )
            deadline = time.monotonic() + self.timeout
            while time.monotonic() < deadline:
                try:
                    packet, _peer = receiver.recvfrom(65535)
                except TimeoutError:
                    continue
                address, value = decode_osc_string(packet)
                if address != ACK_ADDRESS:
                    continue
                parts = value.split("|")
                if len(parts) == 2 and parts[0] == nonce and parts[1].isdigit():
                    return int(parts[1])
        raise Ma3OscError(
            "No MA3 OSC output line replied (tested lines 1-8). Check Destination IP, Send, and ports."
        )

    def scan(self, lua_path_on_ma3: str) -> Ma3PoolSnapshot:
        scan_id = uuid.uuid4().hex[:12]
        maxima: dict[str, int] = {}
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as receiver:
            receiver.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            receiver.bind(("", self.listen_port))
            receiver.settimeout(0.25)
            safe_id = scan_id.replace('"', "")
            safe_path = lua_path_on_ma3.replace('"', "")
            self._send_command(f'SetGlobalVariable "cueplayer_scan_id" "{safe_id}"')
            self._send_command(f'LuaFile "{safe_path}"')
            deadline = time.monotonic() + self.timeout
            while time.monotonic() < deadline:
                try:
                    packet, _peer = receiver.recvfrom(65535)
                except TimeoutError:
                    continue
                address, value = decode_osc_string(packet)
                if address == DONE_ADDRESS and value == scan_id:
                    return Ma3PoolSnapshot(maxima=maxima, scan_id=scan_id)
                if address != SCAN_ADDRESS:
                    continue
                parts = value.split("|")
                if len(parts) == 3 and parts[0] == scan_id and parts[2].isdigit():
                    maxima[parts[1]] = int(parts[2])
        raise Ma3OscError(
            "No MA3 scan reply. Check OSC Input /cmd, OSC Output destination, ports, and LuaFile path."
        )
