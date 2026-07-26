"""
Audio routing spike for CuePlayer.

Goal:
  - List Windows output devices / channel counts
  - Load a stereo file from a Chinese path (L = LTC stand-in, R = Music)
  - Route R -> device CH1+CH2, L -> device CH3
  - Exercise play / seek / stop via sounddevice callback

Run:
  .\\.venv\\Scripts\\python.exe -m cueplayer.spikes.audio_routing
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
import time
import wave
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import sounddevice as sd

from cueplayer.routing.matrix import apply_routing, warn_if_outputs_insufficient


SAMPLE_RATE = 48000


@dataclass
class SpikeResult:
    ok: bool
    message: str
    details: dict


def list_devices() -> list[dict]:
    hostapis = sd.query_hostapis()
    devices = []
    for index, device in enumerate(sd.query_devices()):
        devices.append(
            {
                "index": index,
                "name": device["name"],
                "max_input_channels": int(device["max_input_channels"]),
                "max_output_channels": int(device["max_output_channels"]),
                "default_samplerate": float(device["default_samplerate"]),
                "hostapi": int(device["hostapi"]),
                "hostapi_name": hostapis[device["hostapi"]]["name"],
            }
        )
    return devices


def pick_multichannel_output(devices: list[dict], prefer_name: str | None = None) -> dict | None:
    candidates = [
        d
        for d in devices
        if d["max_output_channels"] >= 4
        and d["hostapi_name"] in {"MME", "Windows DirectSound", "Windows WDM-KS"}
    ]
    if prefer_name:
        for d in candidates:
            if prefer_name.lower() in d["name"].lower():
                return d
    # Prefer VB-Audio 16ch if present (useful when Focusrite is unplugged).
    for d in candidates:
        if "16ch" in d["name"].lower() or "cable in 16" in d["name"].lower():
            return d
    for d in candidates:
        if "focusrite" in d["name"].lower() or "scarlett" in d["name"].lower():
            return d
    return candidates[0] if candidates else None


def write_stereo_test_wav(path: Path, seconds: float = 4.0) -> Path:
    """
    Create stereo fixture:
      L (ch0) = 1 kHz tone  -> stands in for LTC
      R (ch1) = 440 Hz tone -> stands in for Music
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    t = np.linspace(0, seconds, int(SAMPLE_RATE * seconds), endpoint=False)
    left = 0.2 * np.sin(2 * np.pi * 1000.0 * t)  # LTC stand-in
    right = 0.25 * np.sin(2 * np.pi * 440.0 * t)  # Music stand-in
    stereo = np.stack([left, right], axis=1)
    pcm = np.clip(stereo * 32767.0, -32768, 32767).astype(np.int16)

    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(2)
        wf.setsampwidth(2)
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(pcm.tobytes())
    return path


def load_wav_stereo(path: Path) -> tuple[np.ndarray, int]:
    with wave.open(str(path), "rb") as wf:
        channels = wf.getnchannels()
        rate = wf.getframerate()
        frames = wf.readframes(wf.getnframes())
        width = wf.getsampwidth()

    if width != 2:
        raise ValueError(f"Spike currently expects 16-bit PCM WAV, got width={width}")

    data = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0
    if channels == 1:
        data = np.stack([data, data], axis=1)
    else:
        data = data.reshape(-1, channels)[:, :2]
    return data, rate


class CallbackPlayer:
    def __init__(
        self,
        audio: np.ndarray,
        sample_rate: int,
        device: int,
        output_channels: int,
        route: dict[int, list[int]],
    ) -> None:
        self.audio = audio
        self.sample_rate = sample_rate
        self.device = device
        self.output_channels = output_channels
        self.route = route
        self.position = 0
        self.lock = threading.Lock()
        self.finished = threading.Event()
        self.stream: sd.OutputStream | None = None

    def _callback(self, outdata, frames, time_info, status) -> None:  # noqa: ANN001
        del time_info, status
        with self.lock:
            start = self.position
            end = min(start + frames, len(self.audio))
            chunk = self.audio[start:end]
            if len(chunk) < frames:
                pad = np.zeros((frames - len(chunk), self.audio.shape[1]), dtype=np.float32)
                chunk = np.concatenate([chunk, pad], axis=0)
                self.finished.set()
            routed = apply_routing(chunk, self.route, self.output_channels)
            outdata[:] = routed
            self.position = end

    def start(self) -> None:
        self.stream = sd.OutputStream(
            samplerate=self.sample_rate,
            channels=self.output_channels,
            dtype="float32",
            device=self.device,
            callback=self._callback,
        )
        self.stream.start()

    def seek(self, seconds: float) -> None:
        with self.lock:
            frame = int(max(0.0, seconds) * self.sample_rate)
            self.position = min(frame, len(self.audio))
            self.finished.clear()

    def stop(self) -> None:
        if self.stream is not None:
            self.stream.stop()
            self.stream.close()
            self.stream = None


def run_spike(play_seconds: float = 2.0, device_name: str | None = None) -> SpikeResult:
    root = Path(__file__).resolve().parents[3]
    fixture_dir = root / "fixtures" / "media" / "中文測試"
    wav_path = fixture_dir / "LTC左_音樂右_測試.wav"
    write_stereo_test_wav(wav_path)

    devices = list_devices()
    multi = [d for d in devices if d["max_output_channels"] >= 4]
    focusrite = [d for d in devices if "focusrite" in d["name"].lower() or "scarlett" in d["name"].lower()]
    chosen = pick_multichannel_output(devices, prefer_name=device_name)

    report = {
        "fixture": str(wav_path),
        "chinese_path_ok": "中文" in str(wav_path),
        "device_count": len(devices),
        "multichannel_outputs": multi,
        "focusrite_detected": focusrite,
        "chosen_device": chosen,
        "hostapis": [{"index": i, "name": h["name"]} for i, h in enumerate(sd.query_hostapis())],
    }

    if chosen is None:
        return SpikeResult(
            ok=False,
            message=(
                "找不到 >=4 聲道的輸出裝置。請接上 Focusrite，"
                "或確認 VB-Audio Cable / 多聲道介面已啟用。"
            ),
            details=report,
        )

    warning = warn_if_outputs_insufficient([0, 1, 2], chosen["max_output_channels"])
    if warning:
        return SpikeResult(ok=False, message=warning, details=report)

    audio, rate = load_wav_stereo(wav_path)
    # Source L=0 (LTC) -> device CH3 (index 2)
    # Source R=1 (Music) -> device CH1+CH2 (index 0,1)
    route = {0: [2], 1: [0, 1]}

    player = CallbackPlayer(
        audio=audio,
        sample_rate=rate,
        device=chosen["index"],
        output_channels=min(4, chosen["max_output_channels"]),
        route=route,
    )

    player.start()
    time.sleep(min(play_seconds, 1.0))
    player.seek(0.5)
    time.sleep(max(0.2, play_seconds - 1.0))
    player.stop()

    report["route"] = {"L_LTC_to": [3], "R_Music_to": [1, 2]}  # 1-based for humans
    report["seek_exercised"] = True
    report["stop_exercised"] = True
    used_focusrite = bool(focusrite) and chosen in focusrite
    report["used_focusrite"] = used_focusrite
    report["note"] = (
        "家用電腦沒有 Focusrite 不算失敗：優先用 Focusrite；否則用 VB-Audio 等多聲道裝置驗證路由矩陣。"
        "公司有 Focusrite 時用同一支 spike 複測，並在 Focusrite Control 將 Playback 1-4 直通 Output 1-4。"
    )

    device_kind = "Focusrite" if used_focusrite else "VB-Audio／多聲道裝置（家用驗證）"
    return SpikeResult(
        ok=True,
        message=(
            f"路由 spike 成功（{device_kind}）：裝置 [{chosen['index']}] {chosen['name']} "
            f"({chosen['hostapi_name']}, {chosen['max_output_channels']} ch)。"
            " R→CH1+CH2、L→CH3；seek/stop 已跑過。"
        ),
        details=report,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="CuePlayer audio routing spike")
    parser.add_argument("--seconds", type=float, default=2.0, help="playback duration")
    parser.add_argument("--device-name", type=str, default=None, help="substring to prefer")
    parser.add_argument(
        "--list-only",
        action="store_true",
        help="only print devices, do not play",
    )
    parser.add_argument(
        "--json-out",
        type=Path,
        default=Path("docs/spikes/audio_routing_result.json"),
        help="where to write the result JSON",
    )
    args = parser.parse_args(argv)

    # Make Windows consoles less likely to garble Chinese device names.
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except Exception:
        pass

    if args.list_only:
        print(json.dumps(list_devices(), ensure_ascii=False, indent=2))
        return 0

    result = run_spike(play_seconds=args.seconds, device_name=args.device_name)
    args.json_out.parent.mkdir(parents=True, exist_ok=True)
    payload = {"ok": result.ok, "message": result.message, "details": result.details}
    args.json_out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(result.message)
    print(f"詳細結果已寫入: {args.json_out}")
    if not result.details.get("focusrite_detected"):
        print("說明：家用機沒有 Focusrite 是正常的；公司接上後再跑同一支指令複測即可。")
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
