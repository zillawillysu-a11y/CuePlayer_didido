# LTC Clip Playback Hot-Path Diagnostic + Minimal Fix

## Task objective

在 `clip_generator` Song 位於合法 gap 時，移除 PortAudio callback 內可避免的 LTC clip 工作，同時保留 active 與 crossing buffer 的 LTC 語意。

## What was implemented

- 追蹤 callback -> `_ltc_chunk()` -> `_clip_ltc_chunk()` -> cached LTC slices -> output routing。
- 在 callback 外建立 immutable frame-interval snapshot，於 async cache 建立前排序 clips 並驗證／parse start TC。
- 新增 binary-search gap fast path：buffer 與半開 `[start, end)` clips 無交集時立即回傳 silence；不掃描 cached table、不讀 mutable Song、不 parse TC、不建 cursor、不產生 waveform。
- 一般 non-overlapping clips 只 slice candidate cached PCM ranges；有效但有 warning 的 overlap 保留保守 mix 行為。
- 新增 lock-free callback PERF aggregation，於稍後發佈 `audio.ltc_clip.*`：lookup/generate mean/max、gap/active count、clip count、boundary-cross count。
- 新增 gap、no-clips、active fallback、crossing 的窄測試。

## Files changed

- `src/cueplayer/playback/audio_engine.py`
- `tests/playback/test_ltc_clip_playback.py`

## Architecture decisions

- Audio sample position 仍是唯一 playback clock。
- callback 不呼叫會 lock 的 `diagnostics.perf`；僅在 PERF enabled 時更新 primitive，並於既有 non-RT report path 發佈。
- UI、MTC、exporter、persistence、routing semantics 與 active clip mapping 均未改動。

## Tests performed

```text
.venv\\Scripts\\python.exe -m pytest -q tests/playback/test_ltc_clip_playback.py tests/domain/test_ltc_clips.py tests/playback/test_audio_engine_source_ltc.py tests/playback/test_audio_engine_generator_stereo_music.py tests/playback/test_ltc_off_strips_from_music.py
55 passed

.venv\\Scripts\\python.exe -m compileall -q src/cueplayer/playback/audio_engine.py
git diff --check
```

一項本機 `.pytest_cache` 存取 warning 未影響執行。

## Remaining issues

- 仍需真實 Windows PERF 驗證：以 `CUEPLAYER_PERF=1` 重現 clip gap，檢查 `audio.ltc_clip.gap_fast_path_count`、`generate_ms` 與 `audio.callback.*`。
- callback 外 full-clip PCM builder 刻意未修改；僅在此修正後仍有 hardware stall 時，才 profile 其 startup GIL cost。

## Suggested next task

執行 focused Windows LTC Clips gap PERF 驗證。若 gap counter 證明此路徑已使用仍有 deadline miss，追查第一個剩餘 Clips-only blocker；否則另行進入 Timeline B2.2。
