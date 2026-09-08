"""Read-only, hardware-free audit probes for d9663ec; prints JSON evidence.

Run with the project Python. No audio stream or network connection is opened.
Temporary codec fixtures are deleted on completion. These characterize the
baseline, rather than asserting that its known defects are correct behavior.
"""
from __future__ import annotations

import ast
import importlib.metadata
import json
import os
from pathlib import Path
import tempfile
import time
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import numpy as np
import soundfile as sf
from PySide6.QtWidgets import QApplication
from cueplayer.media.audio_loader import AudioBuffer, build_peak_pyramid, choose_peak_level, load_audio
from cueplayer.playback.audio_engine import AudioEngine
from cueplayer.playback.mtc_output import MtcOutput
from cueplayer.playback.resample import resample_linear
from cueplayer.timecode.smpte import seconds_to_timecode, timecode_to_seconds


def main() -> None:
    app = QApplication.instance() or QApplication([])
    results = {"baseline": "d9663ec", "hardware_output_tested": False}
    results["packages"] = {p: importlib.metadata.version(p) for p in
        ("numpy", "soundfile", "sounddevice", "av", "PySide6", "pytest")}
    root = Path(__file__).resolve().parents[1]
    inventory = []
    for p in sorted((root / "src").rglob("*.py")):
        source = p.read_text(encoding="utf-8-sig")
        tree = ast.parse(source)
        inventory.append({"file": p.relative_to(root).as_posix(),
            "lines": len(source.splitlines()),
            "functions": sum(isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) for n in ast.walk(tree))})
    results["source_inventory"] = inventory

    mono, levels = build_peak_pyramid(np.zeros((48000, 2), np.float32), 48000)
    results["peak_selection"] = {str(spp): choose_peak_level(levels, spp).samples_per_bucket
        for spp in (1, 48, 192, 768, 3072, 480000)}
    tail = np.zeros((48001, 2), np.float32)
    tail[-1] = 1
    _, tail_levels = build_peak_pyramid(tail, 48000)
    results["tail_transient_peak_max"] = [float(x.maxs.max()) for x in tail_levels]
    stereo = np.stack([np.ones(48000), -np.ones(48000)], axis=1).astype(np.float32)
    results["antiphase_waveform_peak"] = float(np.abs(build_peak_pyramid(stereo, 48000)[0]).max())

    engines = []
    def engine():
        e = AudioEngine()
        engines.append(e)
        return e

    e = engine()
    e._playing = True
    e._playback_rate = 48000
    with patch("cueplayer.playback.audio_engine.time.monotonic", return_value=100.0):
        e._make_stream_callback(48000)(np.empty((480, 2), np.float32), 480,
            SimpleNamespace(currentTime=100.0, outputBufferDacTime=100.03), SimpleNamespace(output_underflow=False))
        results["clock_at_callback"] = {"reported_seconds": e.position,
            "first_sample_dac_delay_seconds": .03, "block_seconds": .01,
            "steady_state_lead_seconds_for_this_schedule": .04}

    e = engine()
    e._playing = True
    e._playback_rate = 48000
    e.loop_enabled = e._loop_engage = True
    e.loop_a, e.loop_b = 0.0, .01
    e._playback_samples = np.repeat(np.arange(96000, dtype=np.float32)[:, None] / 100000, 2, axis=1)
    out = np.empty((1024, 2), np.float32)
    e._make_stream_callback(48000)(out, 1024, None, SimpleNamespace(output_underflow=False))
    results["short_loop"] = {"loop_frames":480, "callback_frames":1024,
        "expected_next_frame":1024 % 480, "actual_next_frame":e._position_frame,
        "expected_sample_1000":float(e._playback_samples[1000 % 480,0]),
        "actual_sample_1000":float(out[1000,0])}

    e = engine()
    e._playback_rate = 48000
    e._position_frame = 480000
    old_ltc = np.ones(480, np.float32)
    e._ltc_pcm = old_ltc
    attempts = []
    class FakeStream:
        def __init__(self, **kwargs):
            attempts.append(kwargs["samplerate"])
            if kwargs["samplerate"] != 96000:
                import sounddevice
                raise sounddevice.PortAudioError("simulated rate rejection")
        def start(self): pass
        def stop(self): pass
        def close(self): pass
    with patch("cueplayer.playback.audio_engine.sd.OutputStream", FakeStream):
        e._start_stream()
        results["fallback_state"] = {"attempted_rates":attempts, "engine_rate":e._playback_rate,
            "mixer_rate":e._video_mixer._playback_rate, "token_rate":e._active_stream_token[2],
            "position_before_seconds":10.0,"position_after_seconds":e.raw_position,
            "old_ltc_retained":e._ltc_pcm is old_ltc}
        e._stop_stream()

    sent = []
    mtc = MtcOutput()
    mtc._enabled = mtc._playing = True
    mtc._port = SimpleNamespace(send=lambda m: sent.append(m))
    mtc._reset_qf_locked(10.0)
    mtc.tick(10.0)
    sent.clear()
    mtc.tick(2.0)
    mtc.tick(3.0)
    results["mtc_backward_wrap"] = {"qf_sent_after_wrap_10_to_2_then_3":len(sent),
        "last_qf_index":mtc._last_qf_index}
    mtc._port = None
    results["ndf_roundtrip"] = {str(fps): {"tc":seconds_to_timecode(3600,fps).format(),
        "back_seconds":timecode_to_seconds(seconds_to_timecode(3600,fps).format(),fps)}
        for fps in (23.976,24,25,29.97,30)}

    # Long-file memory is arithmetic only: do not allocate a multi-hour PCM.
    results["three_hour_stereo_float32_bytes"] = {str(sr): {
        "native_pcm":10800*sr*2*4,"display_mono":10800*sr*4,
        "ltc_pcm":10800*sr*4} for sr in (44100,48000,96000)}
    results["rate_conversion"] = []
    for src, dst in ((44100,48000),(48000,48000),(48000,96000),(96000,48000)):
        a = np.sin(2*np.pi*1000*np.arange(src*2)/src).astype(np.float32)
        b = resample_linear(a,src,dst)
        freq = float(np.argmax(np.abs(np.fft.rfft(b))) * dst / len(b))
        results["rate_conversion"].append({"src":src,"dst":dst,"seconds":len(b)/dst,"tone_hz":freq})
    a = np.sin(2*np.pi*30000*np.arange(96000)/96000).astype(np.float32)
    b = resample_linear(a,96000,48000)
    results["downsample_alias"] = {"src_hz":30000,"output_peak_hz":int(np.argmax(np.abs(np.fft.rfft(b)))),
        "output_rms":float(np.sqrt(np.mean(b*b)))}

    results["codec_clicks"] = []
    with tempfile.TemporaryDirectory(prefix="cueplayer_audit_") as td:
        for sr in (44100,48000,96000):
            a = np.zeros((sr*4,2),np.float32)
            for sec in range(4):
                a[sec*sr:sec*sr+8] = .8
            for fmt, suffix in (("WAV","wav"),("FLAC","flac"),("MP3","mp3")):
                p = Path(td) / f"節拍_{sr}.{suffix}"
                try:
                    sf.write(p,a,sr,format=fmt)
                    buf = load_audio(p)
                    detected = []
                    for sec in range(4):
                        center = sec*buf.sample_rate
                        lo, hi = max(0,center-2000), min(buf.frames,center+2000)
                        detected.append((lo+int(np.argmax(np.abs(buf.samples[lo:hi,0])))-center)/buf.sample_rate*1000)
                    results["codec_clicks"].append({"format":fmt,"requested_sr":sr,
                        "decoded_sr":buf.sample_rate,"seconds":buf.duration_seconds,"peak_delta_ms":detected})
                except Exception as exc:
                    results["codec_clicks"].append({"format":fmt,"requested_sr":sr,"error":str(exc)})
        # Check real PyAV sequential-batch coverage, using a tiny generated WAV.
        from cueplayer.media.video_waveform_artifact import SequentialWaveformDecoder
        p = Path(td) / "batch_48000.wav"
        sf.write(p, np.ones((48000*25,2),np.float32)*.1,48000)
        decoder = SequentialWaveformDecoder(p)
        batches = []
        try:
            decoder.ensure_open()
            for _ in range(5):
                b = decoder.read_batch(max_seconds=8)
                batches.append({"kind":b.kind,"origin":b.origin_seconds,"duration":b.duration_seconds})
                if b.kind == "eof": break
        finally:
            decoder.close()
        results["sequential_waveform_batches"] = batches

    # Bounded local CPU microbenchmarks, not an audio-device latency claim.
    from cueplayer.domain.models import Song, VideoClip
    for count in (0,100,1000):
        e = engine()
        song = Song.create("audit")
        song.video_clips = [VideoClip.create(f"v{i}",Path("unused.mp4"),start_seconds=i*2,
            duration_seconds=1) for i in range(count)]
        e._video_mixer._song = song
        e._video_mixer.muted = False
        times = []
        for _ in range(50):
            t0 = time.perf_counter()
            e._video_mixer.chunk_at(48000*2500,256)
            times.append((time.perf_counter()-t0)*1000)
        results.setdefault("mixer_offscreen_clip_scan_ms",[]).append({"clips":count,
            "median":float(np.median(times)),"p95":float(np.percentile(times,95))})
    for e in engines:
        e._playing = False
        for pool in (e._ltc_executor,e._resample_executor,e._ltc_detect_executor,e._video_mixer._executor):
            pool.shutdown(wait=True,cancel_futures=True)
    print(json.dumps(results,ensure_ascii=False,indent=2))


if __name__ == "__main__":
    main()
