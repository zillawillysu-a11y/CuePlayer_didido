# Audio Timing Reliability — LTC Startup + DirectSound/MTC

Date: 2026-09-08
Branch: `technical-audit-0815-028d`
Baseline: `4c866020ffd3434ed35186569ae0c6ccfd4fee8b`

## Task objective

將兩個實機問題分開調查：Problem A（LTC Enable 後約 6 秒 transient theater-audio stutter）與 Problem B（DirectSound + MTC 持續 severe stutter）；先建立 evidence，再只修已被支持的 root cause。

## What was implemented

### Problem A — **Strong evidence but not yet proven on post-fix hardware**

完整 lifecycle：Monitor quick toggle / Audio dialog 寫入 `AudioOutputSettings.ltc_enabled` → `MainWindow._on_output_quick_toggle()` / `_open_audio_midi_settings()` → `AudioEngine.apply_audio_settings()`（GUI thread；若正在播放先 pause）→ `_resolve_device_and_route()` → resolved LTC mode 三選一 → clip mode `_ensure_clip_ltc_cache()` → single-worker `ltc-cache` executor → 每 clip `generate_ltc_pcm()` → 每 clip incremental publish 至 `_ltc_clip_pcm`（短暫 acquire `AudioEngine._lock`）→ `_done()` publish complete cache key → callback 對 ready clip slice cache、pending active clip 用 bounded cursor、gap 直接 silence。

實機舊 PERF dump（2026-09-07 16:02 UTC）有 15 clips、`builder_job_started=2`、`builder_job_completed=2`、`builder_duplicate_suppressed=4`、30 個 clip samples。`builder_clip_ms mean=404.33 / max=787.06`；兩個完整 job 分別約 6.02–6.14 秒（mean 6.083 秒）。`15 × 404 ms ≈ 6.06 秒`，與使用者 A2「LTC ON 立即卡、約 6 秒後恢復」時間尺度吻合。舊 dump 沒有 timestamp event ring，因此尚不能用同一份檔案精確證明 T0/T1/Tn；本輪加入 bounded `audio.ltc_clip.builder_event_ring`，記錄 Enable change、job start、每 clip completion、job complete/cancel，並在事件中 snapshot callback count / interval misses / exec-over-budget，供下一次實機 A/B 直接對時。

Root-cause evidence：舊 `generate_ltc_pcm()` 是 while-per-frame → `encode_ltc_frame_bits()` Python work → `_biphase_encode()` 80-bit Python loop + slice assignments；ThreadPoolExecutor 只把它搬到背景 Python thread，仍與 sounddevice Python callback 爭 GIL。降低 OS thread priority 不改 GIL ownership。舊 cancellation 只在 clip 邊界檢查；incremental publish 改善「cache 何時可用」，不降低約 6 秒的 CPU/GIL 總工作。

Production fix：`generate_ltc_pcm()` 改成 bounded（2048 LTC frames/batch）NumPy/native transition + uint8 parity-cumsum renderer；保留 cumulative rounding、bit boundaries、mid-cell transition、polarity correction、TC rollover、尾端不足 160 samples 留白等既有 semantics。Python 不再 per frame/per bit/per sample render。觀測 benchmark：

- 60 s：scalar 86.9 ms → vectorized 12.9 ms（6.73×）
- 300 s：scalar 451.2 ms → vectorized 64.9 ms（6.96×）
- 15 × 270 s：scalar 6.0947 s → vectorized 0.9036 s（6.74×）

固定 inputs 對舊 scalar reference 為 byte-exact，涵蓋 24/25/30/29.97、drop-frame flag、跨午夜、短 clip、非整秒與跨 2048-frame batch boundary。既有 clip boundary、gap、full-track、decode、MTC mapping tests 保持通過。Generation 仍只在 `ltc-cache` worker；callback 未加入 LTC full generation、wait、join、I/O、Qt、logging 或 unbounded loop。

Builder 行為釐清：clip Enable 會 build 所有有效 clips；same key + same generation 的重複 ensure 會 suppress。Toggle OFF 會 invalidate；再 ON 會 rebuild。clip stale job 在下一 clip boundary cancel 且 stale PCM 不 publish。Full-track 與 clip mode 在同一時刻互斥且共用 single-worker executor，所以不會同時執行；但 mode 快速切換時，舊 full-track future 沒有 generation cancellation，可能先跑完再讓 clip job接手。Vectorization 已將其 lifetime 同樣縮短，但這個 full-track stale-job lifecycle debt 未在本輪擴大重構。

### Problem B — **Not reproduced / insufficient evidence**

目前 stream path 對 ASIO / DirectSound 都要求 `float32`、resolved sample rate/channels、`blocksize=0`（backend-controlled），先試 `latency="low"`，失敗再用 backend default。此機唯讀 device query：Focusrite DirectSound endpoint 為 4ch / default 44.1 kHz / low latency 120 ms / high 240 ms；Focusrite ASIO 為 4ch / default 48 kHz / reported low/high 21.333 ms。實際播放仍可能依 source/device negotiation 開在不同 rate，必須以新 stream metrics 看 live stream，不能用 default 值猜。

舊 dump 只有最後 callback 的 `expected_period_s=10 ms`，沒有 host API、device、output latency 或 frame distribution；其 interval mean 15.30 ms / max 33.68 ms、exec mean 0.389 ms / max 16.91 ms、underflow 0、status 0。舊 `deadline_miss_count=2280/5266` 實際只是 callback invocation interval threshold，不是 PortAudio underflow，且不能確認該 dump 屬哪個 backend。

本輪新增：

- `audio.stream.requested_blocksize/sample_rate/host_api/device/device_index/dtype/channels/requested_latency/output_latency`
- `audio.callback.frame_count_min/max/mean` 與 `actual_period_expected_from_frames_ms`
- `audio.callback.interval_miss_count` 與 `exec_over_budget_count` 分離；保留 `deadline_miss_count` 作 interval-miss backward-compatible alias
- `audio.callback.lock_wait_ms/mean/max`；timer 明確從 acquire callback-wide `AudioEngine._lock` 前開始，完整 exec timer 也本來就在 acquire 前，因此舊 exec 已包含 lock wait
- `mtc.loop_ms/mean/max`、`mtc.clock_lock_wait_ms/mean/max`、`mtc.send_ms/mean/max/count`

MTC lifecycle：Play 後 dedicated daemon `mtc-tick` thread 以 `Event.wait(0.004)` pacing → 讀 sample-clock position → file-LTC sync / loop/source discontinuity re-anchor → `MtcOutput.tick()` → quarter-frame message → MIDI port send。MTC 每 tick 讀 `raw_position` 時會短暫 acquire callback 共用的 `AudioEngine._lock`；新 metric 精確只量 acquire wait。讀完 position 後 lock 已釋放；MIDI send 發生在獨立的 `MtcOutput._lock` 下，deterministic test 證明 send 當下 `AudioEngine._lock` 可立即取得。沒有證據顯示 MTC 改變 audio sample cursor；variable callback frames 與 interleaved MTC ticks 測得 cursor 仍精確等於 frames sum。

因此本輪不宣稱 DirectSound + MTC root cause，也沒有任意放慢 MTC、放大 buffer、關 quarter-frame 或改 AudioEngine lock architecture。下一次 B1–B4 實機 dump 必須找出 DirectSound + MTC ON 唯一惡化的 `frame_count`、interval、exec、callback lock wait、MTC clock wait、loop 或 send 指標後，才選 production fix。

## Files changed

- `src/cueplayer/timecode/ltc.py`
- `src/cueplayer/playback/audio_engine.py`
- `src/cueplayer/playback/mtc_output.py`
- `tests/timecode/test_ltc.py`
- `tests/playback/test_ltc_clip_builder.py`
- `tests/playback/test_audio_timing_diagnostics.py`
- `tests/playback/test_audio_mtc_timing_reliability.py`（new）
- `.ai/REPORT.md`
- `.ai/NEXT_TASK.md`
- `.ai/handoffs/2026-09-08_AudioTiming_LTCStartup_DirectSoundMTC.md`

## Architecture decisions

- Playback Engine sample position remains the only clock；沒有第二個 video/MTC clock。
- Problem A 只替換 encoder implementation；LTC protocol/waveform/TC mapping/cache/clip gap semantics 不變。
- NumPy batch generation 只在 `ltc-cache` worker；callback 保持 bounded cache slice / cursor fallback。
- Problem B 只加 lock-free callback counters與 background-thread local aggregation；report 時才 publish 到 PERF。MTC send timing 在 `CUEPLAYER_PERF` disabled 時不呼叫 timer。
- 沒有改 Timeline、Marks、Clean Video UI、Art-Net、exporter、persistence 或 MA。

## Tests performed

```text
Focused final audio/LTC/MTC batch: 114 passed

Broader non-video playback/timecode batch: 276 passed, 3 failed
- 2 known baseline failures: test_song_use_left_ltc routing expectations
- 1 environment-specific NDI test: installed Program Files NDI runtime adds an extra valid path

Unfiltered tests/playback sweep: NOT COMPLETE
- hit the repository's known Windows native access violation in test_video_sync
  background PyAV decoder (av_path_lock/open_media_decoder); do not count as green.

python -m compileall (touched source): passed
git diff --check: passed (only expected LF→CRLF notices)
```

所有新 correctness tests 不使用 fragile wall-clock thresholds。Benchmark 數字是 diagnostic observation，不是 CI assertion。

## Remaining issues

- Problem A 必須用相同劇場 Song 做 post-fix A1/A2/A3 硬體驗證；預期 builder lifetime 約由 6 秒降到約 1 秒以下，且 native NumPy 工作不再造成相同 GIL starvation。未做此 run 前維持 **Strong evidence but not yet proven**。
- Problem B 必須做 ASIO/DirectSound × MTC OFF/ON 四格實機 A/B；目前為 **Not reproduced / insufficient evidence**，不可猜 production fix。
- 若 B4 唯一升高 callback lock wait / MTC clock wait，下一個 narrow candidate 才是 lock-free bounded clock snapshot；若 send/loop 升高則調查 MIDI backend blocking/GIL；若只有 interval miss 但 frame-derived period、underflow/status、exec 都正常，先修 diagnostic interpretation，不動播放。
- Full-track LTC stale future 尚無 generation-aware cancellation；向量化後成本已大幅降低，但 lifecycle debt仍應在有實機 evidence 時另案處理。
- `.pytest_cache` 仍有既有 Windows access-denied warning；與本輪功能無關。

## Suggested next task

在劇場硬體執行同一 Song 的 A1/A2/A3 與 B1–B4 `CUEPLAYER_PERF=1` matrix，使用新 `builder_event_ring`、stream config、frame distribution、callback lock wait、MTC loop/clock-lock/send metrics：先確認 Problem A post-fix，再找出 DirectSound + MTC ON 唯一惡化因素；只有 evidence 指向單一機制後才實作 Problem B narrow fix。
