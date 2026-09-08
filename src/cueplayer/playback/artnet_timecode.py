"""Art-Net 4 ArtTimeCode output driven by CuePlayer's sample-clock snapshot.

Protocol authority: Art-Net 4 Protocol Release V1.4, Document Revision 1.4dp
(23/10/2025), published by Artistic Licence.  This module implements output
only: no UDP receive, discovery, chase, ArtDmx, or master/slave logic.
"""

from __future__ import annotations

import ipaddress
import logging
import socket
import threading
import time
from dataclasses import dataclass
from typing import Callable, Protocol

from cueplayer.diagnostics import perf as perf_diag
from cueplayer.timecode.smpte import Timecode, parse_timecode

log = logging.getLogger(__name__)

ARTNET_ID = b"Art-Net\x00"
ARTNET_PORT = 0x1936  # 6454; official source and destination UDP port.
ARTNET_PROTOCOL_VERSION = 14
ARTNET_OPCODE_TIMECODE = 0x9700
ARTNET_STREAM_MASTER = 0x00

ARTNET_TYPE_FILM = 0
ARTNET_TYPE_EBU = 1
ARTNET_TYPE_DROP_FRAME = 2
ARTNET_TYPE_SMPTE = 3

SUPPORTED_FPS = (24.0, 25.0, 29.97, 30.0)

# frame, epoch_frame, epoch_mono, playing, scrubbing, sample_rate, generation
ClockSnapshot = tuple[int, int, float, bool, bool, int, int]


class _DatagramSocket(Protocol):
    def setblocking(self, flag: bool) -> None: ...

    def setsockopt(self, level: int, option: int, value: int) -> None: ...

    def bind(self, address: tuple[str, int]) -> None: ...

    def sendto(self, data: bytes, address: tuple[str, int]) -> int: ...

    def close(self) -> None: ...


@dataclass(frozen=True, slots=True)
class Ipv4Interface:
    name: str
    address: str
    netmask: str
    broadcast: str

    @property
    def label(self) -> str:
        return f"{self.name} — {self.address} → {self.broadcast}"


@dataclass(frozen=True, slots=True)
class ArtNetTimecodeStatus:
    enabled: bool
    running: bool
    source: str
    destination: str
    error: str | None
    send_count: int


def normalize_artnet_fps(value: float) -> float:
    fps = float(value)
    for supported in SUPPORTED_FPS:
        if abs(fps - supported) < 0.02:
            return supported
    raise ValueError("ArtTimeCode FPS must be 24, 25, 29.97 DF, or 30.")


def artnet_timecode_type(fps: float) -> int:
    normalized = normalize_artnet_fps(fps)
    if normalized == 24.0:
        return ARTNET_TYPE_FILM
    if normalized == 25.0:
        return ARTNET_TYPE_EBU
    if normalized == 29.97:
        return ARTNET_TYPE_DROP_FRAME
    return ARTNET_TYPE_SMPTE


def build_art_timecode_packet(
    timecode: Timecode,
    fps: float,
    *,
    stream_id: int = ARTNET_STREAM_MASTER,
) -> bytes:
    """Encode the official 19-byte ArtTimeCode packet payload."""
    normalized = normalize_artnet_fps(fps)
    nominal = 30 if normalized in (29.97, 30.0) else int(normalized)
    if not (0 <= timecode.hours <= 23):
        raise ValueError("ArtTimeCode hours must be in 0..23.")
    if not (0 <= timecode.minutes <= 59 and 0 <= timecode.seconds <= 59):
        raise ValueError("ArtTimeCode minutes and seconds must be in 0..59.")
    if not (0 <= timecode.frames < nominal):
        raise ValueError(f"ArtTimeCode frames must be in 0..{nominal - 1}.")
    if not (0 <= int(stream_id) <= 0xFF):
        raise ValueError("ArtTimeCode StreamId must be in 0..255.")
    return (
        ARTNET_ID
        + ARTNET_OPCODE_TIMECODE.to_bytes(2, "little")
        + bytes(
            (
                0,
                ARTNET_PROTOCOL_VERSION,
                0,
                int(stream_id),
                timecode.frames,
                timecode.seconds,
                timecode.minutes,
                timecode.hours,
                artnet_timecode_type(normalized),
            )
        )
    )


def _drop_frame_number(tc: Timecode) -> int:
    """Convert a 29.97 DF label to its continuous frame number."""
    if not (0 <= tc.hours <= 23 and 0 <= tc.minutes < 60 and 0 <= tc.seconds < 60):
        raise ValueError("Invalid 29.97 drop-frame timecode.")
    if not (0 <= tc.frames < 30):
        raise ValueError("29.97 drop-frame frames must be in 0..29.")
    if tc.seconds == 0 and tc.minutes % 10 != 0 and tc.frames < 2:
        raise ValueError("Invalid 29.97 DF label: frames 00 and 01 are dropped here.")
    total_minutes = tc.hours * 60 + tc.minutes
    nominal = ((tc.hours * 3600 + tc.minutes * 60 + tc.seconds) * 30) + tc.frames
    return nominal - 2 * (total_minutes - total_minutes // 10)


def _drop_frame_timecode(frame_number: int) -> Timecode:
    """Convert a continuous 29.97 frame number to a legal 24-hour DF label."""
    frames_per_24_hours = 2_589_408
    frames_per_10_minutes = 17_982
    frames_per_minute = 1_798
    value = int(frame_number) % frames_per_24_hours
    ten_minute_blocks, remainder = divmod(value, frames_per_10_minutes)
    dropped = 18 * ten_minute_blocks
    if remainder >= 2:
        dropped += 2 * ((remainder - 2) // frames_per_minute)
    nominal = value + dropped
    frames = nominal % 30
    total_seconds = nominal // 30
    seconds = total_seconds % 60
    total_minutes = total_seconds // 60
    minutes = total_minutes % 60
    hours = (total_minutes // 60) % 24
    return Timecode(hours, minutes, seconds, frames)


def artnet_timecode_at(
    start_timecode: str,
    position_seconds: float,
    fps: float,
) -> Timecode:
    """Map playback seconds to the selected ArtTimeCode label."""
    normalized = normalize_artnet_fps(fps)
    start = parse_timecode(start_timecode)
    if start is None:
        raise ValueError("ArtTimeCode needs a valid Song Start TC (HH:MM:SS:FF).")
    position = max(0.0, float(position_seconds))
    if normalized == 29.97:
        elapsed = int(position * (30_000.0 / 1_001.0) + 1e-9)
        return _drop_frame_timecode(_drop_frame_number(start) + elapsed)
    nominal = int(normalized)
    if not (0 <= start.frames < nominal):
        raise ValueError(f"Song Start TC frames must be in 0..{nominal - 1}.")
    start_frames = (
        ((start.hours * 60 + start.minutes) * 60 + start.seconds) * nominal
        + start.frames
    )
    total = (start_frames + int(position * normalized + 1e-9)) % (24 * 3600 * nominal)
    frames = total % nominal
    total //= nominal
    seconds = total % 60
    total //= 60
    minutes = total % 60
    hours = (total // 60) % 24
    return Timecode(hours, minutes, seconds, frames)


def list_ipv4_interfaces() -> list[Ipv4Interface]:
    """Return active, non-loopback IPv4 choices including directed broadcast."""
    try:
        from PySide6.QtNetwork import QAbstractSocket, QNetworkInterface
    except Exception:  # pragma: no cover - PySide6 is a production dependency
        return []

    out: list[Ipv4Interface] = []
    seen: set[str] = set()
    ipv4 = QAbstractSocket.NetworkLayerProtocol.IPv4Protocol
    for interface in QNetworkInterface.allInterfaces():
        flags = interface.flags()
        if not (flags & QNetworkInterface.InterfaceFlag.IsUp):
            continue
        if flags & QNetworkInterface.InterfaceFlag.IsLoopBack:
            continue
        for entry in interface.addressEntries():
            if entry.ip().protocol() != ipv4:
                continue
            address = entry.ip().toString()
            netmask = entry.netmask().toString()
            broadcast = entry.broadcast().toString()
            if not address or not netmask:
                continue
            if not broadcast:
                try:
                    network = ipaddress.IPv4Network(f"{address}/{netmask}", strict=False)
                    broadcast = str(network.broadcast_address)
                except ValueError:
                    continue
            if address in seen or broadcast == "255.255.255.255":
                continue
            seen.add(address)
            out.append(
                Ipv4Interface(
                    name=interface.humanReadableName() or interface.name(),
                    address=address,
                    netmask=netmask,
                    broadcast=broadcast,
                )
            )
    return sorted(out, key=lambda item: (not item.address.startswith(("2.", "10.")), item.name))


def validate_artnet_destination(
    local_ip: str,
    mode: str,
    destination_ip: str,
) -> tuple[str, str, str]:
    """Validate and normalize the configured source/casting addresses."""
    local = str(ipaddress.IPv4Address(str(local_ip).strip()))
    destination = str(ipaddress.IPv4Address(str(destination_ip).strip()))
    casting = str(mode or "broadcast").strip().lower()
    if casting not in {"broadcast", "unicast"}:
        raise ValueError("ArtTimeCode destination mode must be broadcast or unicast.")
    if destination == "255.255.255.255":
        raise ValueError("Art-Net forbids the limited broadcast 255.255.255.255.")
    if casting == "broadcast":
        match = next((item for item in list_ipv4_interfaces() if item.address == local), None)
        if match is not None and destination != match.broadcast:
            raise ValueError(
                f"Broadcast destination for {local} must be {match.broadcast}, "
                "the interface directed broadcast."
            )
    return local, casting, destination


class ArtNetTimecodeOutput:
    """One idempotent, non-GUI ArtTimeCode UDP sender."""

    def __init__(
        self,
        clock_snapshot: Callable[[], ClockSnapshot],
        *,
        socket_factory: Callable[..., _DatagramSocket] = socket.socket,
        status_callback: Callable[[], None] | None = None,
        timecode_sync_callback: Callable[[float], None] | None = None,
    ) -> None:
        self._clock_snapshot = clock_snapshot
        self._socket_factory = socket_factory
        self._status_callback = status_callback
        self._timecode_sync_callback = timecode_sync_callback
        self._lock = threading.RLock()
        self._enabled = False
        self._playing = False
        self._fps = 30.0
        self._start_timecode = "01:00:00:00"
        self._local_ip = ""
        self._destination_mode = "broadcast"
        self._destination_ip = ""
        self._socket: _DatagramSocket | None = None
        self._error: str | None = None
        self._send_count = 0
        self._first_send_mono = 0.0
        self._last_frame_key: tuple[int, int] | None = None
        self._clock_generation: int | None = None
        self._clock_floor: float | None = None
        self._force_send = False
        self._stop_event = threading.Event()
        self._wake_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._live_worker_count = 0

    @property
    def enabled(self) -> bool:
        with self._lock:
            return self._enabled

    @property
    def running(self) -> bool:
        with self._lock:
            return bool(self._thread is not None and self._thread.is_alive())

    def status(self) -> ArtNetTimecodeStatus:
        with self._lock:
            return ArtNetTimecodeStatus(
                enabled=self._enabled,
                running=bool(self._thread is not None and self._thread.is_alive()),
                source=f"{self._local_ip}:{ARTNET_PORT}" if self._local_ip else "",
                destination=(
                    f"{self._destination_ip}:{ARTNET_PORT}"
                    if self._destination_ip
                    else ""
                ),
                error=self._error,
                send_count=self._send_count,
            )

    def timecode_at(self, position_seconds: float) -> Timecode:
        with self._lock:
            start_timecode = self._start_timecode
            fps = self._fps
        return artnet_timecode_at(start_timecode, position_seconds, fps)

    def configure(
        self,
        *,
        enabled: bool,
        fps: float,
        start_timecode: str,
        local_ip: str,
        destination_mode: str,
        destination_ip: str,
    ) -> str | None:
        self.on_pause()
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                self._error = "Art-Net Timecode sender did not stop; configuration unchanged."
                self._notify_status()
                return self._error
        self._close_socket()
        udp: _DatagramSocket | None = None
        try:
            normalized_fps = normalize_artnet_fps(fps)
        except ValueError as exc:
            with self._lock:
                self._enabled = bool(enabled)
                self._error = f"Art-Net Timecode: {exc}"
            self._notify_status()
            return self._error
        with self._lock:
            self._enabled = bool(enabled)
            self._fps = normalized_fps
            self._start_timecode = str(start_timecode or "01:00:00:00")
            self._error = None
            self._send_count = 0
            self._first_send_mono = 0.0
            self._last_frame_key = None
            self._clock_generation = None
            self._clock_floor = None
            if not self._enabled:
                self._local_ip = str(local_ip or "")
                self._destination_mode = str(destination_mode or "broadcast")
                self._destination_ip = str(destination_ip or "")
                self._notify_status()
                return None
        try:
            # Validate the timebase before opening a network resource.
            artnet_timecode_at(self._start_timecode, 0.0, self._fps)
            local, casting, destination = validate_artnet_destination(
                local_ip, destination_mode, destination_ip
            )
            udp = self._socket_factory(socket.AF_INET, socket.SOCK_DGRAM)
            udp.setblocking(False)
            udp.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            if casting == "broadcast":
                udp.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            udp.bind((local, ARTNET_PORT))
        except Exception as exc:  # noqa: BLE001 - surfaced as a settings error
            try:
                if udp is not None:
                    udp.close()
            except Exception:
                pass
            with self._lock:
                self._socket = None
                self._error = f"Art-Net Timecode: {exc}"
            self._notify_status()
            return self._error
        with self._lock:
            self._local_ip = local
            self._destination_mode = casting
            self._destination_ip = destination
            self._socket = udp
        self._notify_status()
        return None

    def set_timebase(self, start_timecode: str) -> None:
        with self._lock:
            self._start_timecode = str(start_timecode or "01:00:00:00")
            self._last_frame_key = None
            self._force_send = self._playing
        self._wake_event.set()

    def set_mirror_origin(self, absolute: Timecode, position_seconds: float) -> None:
        """Align ArtTimeCode to decoded file LTC at one playback position."""
        with self._lock:
            fps = self._fps
            rate = 30_000.0 / 1_001.0 if fps == 29.97 else fps
            delta = -int(round(max(0.0, float(position_seconds)) * rate))
            if fps == 29.97:
                origin = _drop_frame_timecode(_drop_frame_number(absolute) + delta)
            else:
                nominal = int(fps)
                total = (
                    ((absolute.hours * 60 + absolute.minutes) * 60 + absolute.seconds)
                    * nominal
                    + absolute.frames
                    + delta
                ) % (24 * 3600 * nominal)
                origin = Timecode(
                    (total // (nominal * 3600)) % 24,
                    (total // (nominal * 60)) % 60,
                    (total // nominal) % 60,
                    total % nominal,
                )
            self._start_timecode = origin.format()
            self._last_frame_key = None

    def on_play(self) -> None:
        with self._lock:
            if not self._enabled or self._socket is None:
                return
            self._playing = True
            self._last_frame_key = None
            self._clock_generation = None
            self._clock_floor = None
            self._force_send = True
        self._start_thread()
        self._wake_event.set()
        self._notify_status()

    def on_seek(self, *, playing: bool) -> None:
        with self._lock:
            self._last_frame_key = None
            self._clock_generation = None
            self._clock_floor = None
            self._force_send = bool(playing and self._enabled and self._socket is not None)
        if self._force_send:
            self._wake_event.set()

    def on_pause(self) -> None:
        with self._lock:
            self._playing = False
            self._force_send = False
        self._stop_thread()
        self._notify_status()

    def close(self) -> None:
        self.on_pause()
        with self._lock:
            self._enabled = False
        self._close_socket()
        self._notify_status()

    def _start_thread(self) -> None:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                if perf_diag.is_enabled():
                    perf_diag.note(
                        "artnet_tc.duplicate_live_sender_count",
                        max(0, self._live_worker_count - 1),
                    )
                return
            self._stop_event.clear()
            thread = threading.Thread(
                target=self._thread_loop,
                name="artnet-timecode",
                daemon=True,
            )
            self._thread = thread
            thread.start()

    def _stop_thread(self) -> None:
        self._stop_event.set()
        self._wake_event.set()
        with self._lock:
            thread = self._thread
        if thread is not None and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=1.0)
        with self._lock:
            if self._thread is thread and (thread is None or not thread.is_alive()):
                self._thread = None
        self._wake_event.clear()

    def _thread_loop(self) -> None:
        with self._lock:
            self._live_worker_count += 1
            duplicate_count = max(0, self._live_worker_count - 1)
            fps = self._fps
        if perf_diag.is_enabled():
            perf_diag.note("artnet_tc.duplicate_live_sender_count", duplicate_count)
        period = 1.0 / fps
        deadline = time.monotonic()
        try:
            while not self._stop_event.is_set():
                now = time.monotonic()
                signalled = self._wake_event.wait(max(0.0, deadline - now))
                self._wake_event.clear()
                if self._stop_event.is_set():
                    break
                woke = time.monotonic()
                lateness = max(0.0, woke - deadline) if not signalled else 0.0
                if perf_diag.is_enabled():
                    perf_diag.record_ms(
                        "artnet_tc.wakeup_lateness_ms", lateness * 1000.0
                    )
                self._tick_once(woke)
                if woke >= deadline:
                    skipped = int((woke - deadline) // period)
                    deadline += (skipped + 1) * period
        except Exception as exc:  # noqa: BLE001 - worker must fail visibly, not silently
            log.exception("Art-Net Timecode sender thread failed")
            with self._lock:
                self._error = f"Art-Net Timecode sender stopped: {exc}"
            self._notify_status()
        finally:
            with self._lock:
                self._live_worker_count = max(0, self._live_worker_count - 1)
                duplicate_count = max(0, self._live_worker_count - 1)
                if self._thread is threading.current_thread():
                    self._thread = None
            if perf_diag.is_enabled():
                perf_diag.note("artnet_tc.duplicate_live_sender_count", duplicate_count)
            self._notify_status()

    def _clock_position(self, now: float) -> tuple[float, int]:
        snapshot = self._clock_snapshot()
        frame, epoch_frame, epoch_mono, playing, scrubbing, sample_rate, generation = snapshot
        rate = float(sample_rate)
        if rate <= 0.0:
            return 0.0, int(generation)
        age = max(0.0, now - float(epoch_mono)) if epoch_mono > 0.0 else 0.0
        if playing and not scrubbing and epoch_mono > 0.0:
            candidate = max(0.0, int(epoch_frame) / rate + min(age, 0.08))
        else:
            candidate = max(0.0, int(frame) / rate)
        generation = int(generation)
        if self._clock_generation != generation:
            self._clock_generation = generation
            self._clock_floor = candidate
        elif self._clock_floor is not None and candidate < self._clock_floor:
            candidate = self._clock_floor
        else:
            self._clock_floor = candidate
        return candidate, generation

    def _tick_once(self, now: float | None = None) -> None:
        current = time.monotonic() if now is None else float(now)
        with self._lock:
            if not self._playing or not self._enabled or self._socket is None:
                return
            udp = self._socket
            fps = self._fps
            destination = (self._destination_ip, ARTNET_PORT)
            force_send = self._force_send
            self._force_send = False
        position, generation = self._clock_position(current)
        if self._timecode_sync_callback is not None:
            try:
                self._timecode_sync_callback(position)
            except Exception as exc:  # noqa: BLE001 - retain last valid TC origin
                log.debug("Art-Net LTC translation refresh failed: %s", exc)
        with self._lock:
            # The translation callback may have re-anchored the origin above.
            start_timecode = self._start_timecode
        rate = 30_000.0 / 1_001.0 if fps == 29.97 else fps
        frame_index = int(position * rate + 1e-9)
        frame_key = (generation, frame_index)
        with self._lock:
            if not force_send and frame_key == self._last_frame_key:
                return
            self._last_frame_key = frame_key
        try:
            tc = artnet_timecode_at(start_timecode, position, fps)
            packet = build_art_timecode_packet(tc, fps)
            send_t0 = time.perf_counter()
            sent = udp.sendto(packet, destination)
            send_ms = (time.perf_counter() - send_t0) * 1000.0
            if sent != len(packet):
                raise OSError(f"short UDP send ({sent}/{len(packet)} bytes)")
        except (BlockingIOError, OSError, ValueError) as exc:
            with self._lock:
                self._error = f"Art-Net Timecode send failed: {exc}"
            if perf_diag.is_enabled():
                perf_diag.count("artnet_tc.send_failures")
            self._notify_status()
            return
        with self._lock:
            self._error = None
            self._send_count += 1
            count = self._send_count
            if self._first_send_mono <= 0.0:
                self._first_send_mono = current
            elapsed = max(1.0 / rate, current - self._first_send_mono)
            sends_per_second = max(0, count - 1) / elapsed
        if perf_diag.is_enabled():
            perf_diag.record_batch(
                spans_ms={"artnet_tc.send_ms": send_ms},
                counters={"artnet_tc.send_count": 1},
                attrs={
                    "artnet_tc.sends_per_second": round(sends_per_second, 3),
                    "artnet_tc.duplicate_live_sender_count": max(
                        0, self._live_worker_count - 1
                    ),
                },
            )

    def _close_socket(self) -> None:
        with self._lock:
            udp = self._socket
            self._socket = None
        if udp is not None:
            try:
                udp.close()
            except Exception:
                pass

    def _notify_status(self) -> None:
        callback = self._status_callback
        if callback is not None:
            try:
                callback()
            except Exception:
                pass
