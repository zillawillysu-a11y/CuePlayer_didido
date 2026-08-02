"""Low-latency WebRTC monitor audio (Opus / UDP) for Safari / iPad Listen.

Sunshine/Moonlight-class approach for the browser: RTCPeerConnection with a
sendonly Opus audio track fed from the CuePlayer music buffer (LTC stripped).
Signaling is HTTP JSON offer/answer on the existing Web Remote server.
"""

from __future__ import annotations

import asyncio
import fractions
import logging
import threading
import time
from typing import Any, Callable

import numpy as np

log = logging.getLogger(__name__)

GetPcmFrameFn = Callable[[int, int], np.ndarray]
LagSkipFn = Callable[[], None]

try:
    from aiortc import (
        RTCConfiguration,
        RTCPeerConnection,
        RTCSessionDescription,
        MediaStreamTrack,
    )
    from aiortc.mediastreams import MediaStreamError
    from av import AudioFrame

    WEBRTC_AVAILABLE = True
except Exception:  # noqa: BLE001
    WEBRTC_AVAILABLE = False
    RTCPeerConnection = Any  # type: ignore[misc, assignment]
    MediaStreamTrack = object  # type: ignore[misc, assignment]
    MediaStreamError = Exception  # type: ignore[misc, assignment]
    AudioFrame = Any  # type: ignore[misc, assignment]


SAMPLE_RATE = 48000
SAMPLES_PER_FRAME = 960  # 20 ms — Opus / WebRTC friendly
# If the sender falls more than this behind wall clock, jump the timeline
# instead of emitting a burst of frames (Safari plays those as speed-up).
LAG_SKIP_SECONDS = 0.06


def pace_monitor_timeline(
    *,
    start: float | None,
    timestamp: int,
    now: float,
    frame_samples: int = SAMPLES_PER_FRAME,
    sample_rate: int = SAMPLE_RATE,
    lag_skip_seconds: float = LAG_SKIP_SECONDS,
) -> tuple[float, int, float, bool]:
    """Advance the monitor presentation clock.

    Returns ``(start, timestamp, sleep_seconds, lag_skipped)``.
    When lag-skipped, the caller should resync the PCM cursor to the engine
    playhead — never dump frames at max rate to "catch up".
    """
    if start is None:
        return now, 0, 0.0, False

    timestamp = int(timestamp) + int(frame_samples)
    due = start + (timestamp / float(sample_rate))
    wait = due - now
    if wait >= 0.0:
        return start, timestamp, wait, False
    if wait > -float(lag_skip_seconds):
        return start, timestamp, 0.0, False

    jumped = int(round((now - start) * float(sample_rate)))
    rem = jumped % int(frame_samples)
    if rem:
        jumped += int(frame_samples) - rem
    timestamp = max(timestamp, jumped)
    return start, timestamp, 0.0, True


class EngineMonitorTrack(MediaStreamTrack):
    """Live music-only mono track locked to the engine playhead."""

    kind = "audio"

    def __init__(
        self,
        get_pcm_frame: GetPcmFrameFn,
        on_lag_skip: LagSkipFn | None = None,
    ) -> None:
        super().__init__()
        self._get_pcm_frame = get_pcm_frame
        self._on_lag_skip = on_lag_skip
        self._timestamp = 0
        self._start: float | None = None

    async def recv(self) -> Any:
        if self.readyState != "live":
            raise MediaStreamError

        now = time.time()
        self._start, self._timestamp, wait, skipped = pace_monitor_timeline(
            start=self._start,
            timestamp=self._timestamp,
            now=now,
        )
        if wait > 0:
            await asyncio.sleep(wait)
        if skipped and self._on_lag_skip is not None:
            try:
                self._on_lag_skip()
            except Exception:  # noqa: BLE001
                log.exception("listen lag-skip callback failed")

        try:
            pcm = self._get_pcm_frame(SAMPLES_PER_FRAME, SAMPLE_RATE)
        except Exception:  # noqa: BLE001
            log.exception("monitor frame failed")
            pcm = np.zeros(SAMPLES_PER_FRAME, dtype=np.int16)

        pcm = np.asarray(pcm, dtype=np.int16).reshape(-1)
        if pcm.size < SAMPLES_PER_FRAME:
            pad = np.zeros(SAMPLES_PER_FRAME - pcm.size, dtype=np.int16)
            pcm = np.concatenate([pcm, pad])
        elif pcm.size > SAMPLES_PER_FRAME:
            pcm = pcm[:SAMPLES_PER_FRAME]

        frame = AudioFrame(format="s16", layout="mono", samples=SAMPLES_PER_FRAME)
        frame.planes[0].update(pcm.tobytes(order="C"))
        frame.pts = self._timestamp
        frame.sample_rate = SAMPLE_RATE
        frame.time_base = fractions.Fraction(1, SAMPLE_RATE)
        return frame


class WebRTCListenHub:
    """One active peer connection; runs an asyncio loop in a daemon thread."""

    def __init__(
        self,
        get_pcm_frame: GetPcmFrameFn,
        on_lag_skip: LagSkipFn | None = None,
    ) -> None:
        self._get_pcm_frame = get_pcm_frame
        self._on_lag_skip = on_lag_skip
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._pc: Any | None = None
        self._track: EngineMonitorTrack | None = None
        self._lock = threading.Lock()

    @property
    def available(self) -> bool:
        return WEBRTC_AVAILABLE

    def start(self) -> None:
        if not WEBRTC_AVAILABLE:
            return
        with self._lock:
            if self._loop is not None:
                return
            loop = asyncio.new_event_loop()
            thread = threading.Thread(
                target=self._run_loop,
                args=(loop,),
                name="cueplayer-webrtc-listen",
                daemon=True,
            )
            self._loop = loop
            self._thread = thread
            thread.start()

    def stop(self) -> None:
        loop = None
        with self._lock:
            loop = self._loop
            self._loop = None
            self._thread = None
        if loop is None:
            return
        try:
            fut = asyncio.run_coroutine_threadsafe(self._shutdown(), loop)
            fut.result(timeout=3.0)
        except Exception:  # noqa: BLE001
            pass
        try:
            loop.call_soon_threadsafe(loop.stop)
        except Exception:  # noqa: BLE001
            pass

    def handle(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Synchronous signaling entry (called from HTTP worker threads)."""
        if not WEBRTC_AVAILABLE:
            return {
                "ok": False,
                "error": "webrtc_unavailable",
                "detail": "aiortc is not installed",
            }
        self.start()
        op = str(payload.get("op") or "").strip().lower()
        if op in ("capabilities", "caps", "ping"):
            return {"ok": True, "webrtc": True, "sample_rate": SAMPLE_RATE, "frame_ms": 20}
        if op == "hangup":
            return self._submit(self._hangup())
        if op in ("offer", "answer_request"):
            return self._submit(self._accept_offer(payload))
        return {"ok": False, "error": "unknown_op", "op": op}

    def _run_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        asyncio.set_event_loop(loop)
        loop.run_forever()
        try:
            pending = asyncio.all_tasks(loop)
            for task in pending:
                task.cancel()
            if pending:
                loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
        except Exception:  # noqa: BLE001
            pass
        finally:
            loop.close()

    def _submit(self, coro: Any) -> dict[str, Any]:
        loop = self._loop
        if loop is None:
            return {"ok": False, "error": "webrtc_not_started"}
        try:
            fut = asyncio.run_coroutine_threadsafe(coro, loop)
            return fut.result(timeout=12.0)
        except Exception as exc:  # noqa: BLE001
            log.exception("webrtc signaling failed")
            return {"ok": False, "error": "webrtc_failed", "detail": str(exc)}

    async def _shutdown(self) -> None:
        await self._close_pc()

    async def _hangup(self) -> dict[str, Any]:
        await self._close_pc()
        return {"ok": True, "op": "hangup"}

    async def _close_pc(self) -> None:
        pc = self._pc
        track = self._track
        self._pc = None
        self._track = None
        if track is not None:
            try:
                track.stop()
            except Exception:  # noqa: BLE001
                pass
        if pc is not None:
            try:
                await pc.close()
            except Exception:  # noqa: BLE001
                pass

    async def _accept_offer(self, payload: dict[str, Any]) -> dict[str, Any]:
        sdp = str(payload.get("sdp") or "")
        typ = str(payload.get("type") or "offer")
        if not sdp:
            return {"ok": False, "error": "missing_sdp"}

        await self._close_pc()

        # LAN-only: no public STUN required for same-WiFi iPad ↔ PC.
        config = RTCConfiguration(iceServers=[])
        pc = RTCPeerConnection(configuration=config)
        track = EngineMonitorTrack(self._get_pcm_frame, on_lag_skip=self._on_lag_skip)
        pc.addTrack(track)
        self._pc = pc
        self._track = track

        @pc.on("connectionstatechange")
        async def _on_state() -> None:
            state = pc.connectionState
            log.info("webrtc connectionState=%s", state)
            if state in ("failed", "closed", "disconnected"):
                # Keep PC until hangup/new offer; track stops with pc.close().
                pass

        offer = RTCSessionDescription(sdp=sdp, type=typ)
        await pc.setRemoteDescription(offer)
        answer = await pc.createAnswer()
        await pc.setLocalDescription(answer)
        await self._wait_ice_complete(pc)

        local = pc.localDescription
        if local is None:
            return {"ok": False, "error": "no_local_description"}
        return {
            "ok": True,
            "op": "answer",
            "type": local.type,
            "sdp": local.sdp,
            "webrtc": True,
            "sample_rate": SAMPLE_RATE,
            "frame_ms": 20,
        }

    async def _wait_ice_complete(self, pc: Any, timeout: float = 4.0) -> None:
        if pc.iceGatheringState == "complete":
            return
        done = asyncio.Event()

        @pc.on("icegatheringstatechange")
        async def _on_ice() -> None:
            if pc.iceGatheringState == "complete":
                done.set()

        if pc.iceGatheringState == "complete":
            return
        try:
            await asyncio.wait_for(done.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            # Partial candidates are often enough on LAN.
            log.warning("webrtc ICE gathering timed out; using partial candidates")
