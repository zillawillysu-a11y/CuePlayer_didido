# LTC Clip Remaining Playback Stall — Builder Diagnostic + Minimal Fix

## Task objective

診斷 LTC Clips 剩餘 playback stall 的第一個 Clips-only 根因（主嫌疑：callback 外 async LTC clip PCM builder 的純 Python GIL / CPU pressure），確認後施以最窄的安全修正，並加低成本 `CUEPLAYER_PERF` 度量與 A/B 結構診斷。

## What was implemented

- 追跡 call chain：`set_song`/`play()`/`apply_audio_settings`/`refresh_song_ltc_routing`/buffer setup → `_ensure_clip_ltc_cache()` → 單一 `ltc-cache` worker → `generate_ltc_pcm()`（純 Python per-frame 編碼）→ 舊 all-or-nothing `_ltc_clip_table` publish。
- Benchmark：≈1.45 ms CPU / 每秒 clip（48 kHz / 30 fps）；60 s clip ≈ 87 ms 連續 GIL；30 min payload ≈ 數秒。
- 實測 A/B（12×60 s clips）：builder active → callback mean 0.08–0.15 ms、max ~2.2 ms spikes；builder idle → mean 0.003 ms、max 0.03 ms。Builder 造成 GIL contention jitter；舊 all-or-nothing + duplicate stacking + 無 cancellation 會放大壓力。
- 修正（`src/cueplayer/playback/audio_engine.py`）：
  1. Incremental per-clip publish（`_ltc_clip_pcm`）：ready clip = NumPy slice，pending clip = bounded O(chunk) fallback；callback 永不 wait builder（無 join/condition/future/IO/Qt）。
  2. Generation-aware duplicate suppression：只 suppress 有效 in-flight（same key + same generation）；stale build 不重用、不疊加。
  3. Cooperative cancellation：invalidation bump `_ltc_clip_generation`；worker 在 clip 邊界檢查 token 停止 stale build。
  4. Builder 降 thread priority（含 full-track LTC builder）。
  5. `clip_generator` 模式跳過檔案 LTC auto-detect scan（該結果 clip 模式從不使用）。
  6. PERF metrics：`builder_job_started/completed/cancelled`、`builder_active_jobs`、`builder_duplicate_suppressed`、`builder_total_ms`、`builder_clip_ms`、`cache_rebuild_count`、`cache_hit`、`cache_miss`。
- 過程中另發現並修正：舊 dedup 把「已 invalidate 的 stale in-flight build」誤判為可重用，會 suppress 掉真正需要的 rebuild（generation-aware 檢查修復）。

## Files changed

- `src/cueplayer/playback/audio_engine.py`
- `tests/playback/test_ltc_clip_playback.py`
- `tests/playback/test_ltc_clip_builder.py`（新增，14 tests）

## Architecture decisions

- Audio sample position 仍為唯一 playback clock。
- Callback 保持無 builder wait、無新 lock/IO/Qt/model parse/unbounded loop；只讀 immutable tuple 與 per-clip dict（GIL atomic 指派）。
- 未改共享受眾 `generate_ltc_pcm` / `LtcPlaybackCursor`（總工作量根治屬後續 task）；未動 Timeline/Mark/Main UI TC/Clean Video/MTC/Art-Net/exporter/persistence。

## Tests performed

```text
QT_QPA_PLATFORM=offscreen .venv\Scripts\python.exe -m pytest -q \
  tests/playback/test_ltc_clip_playback.py tests/playback/test_ltc_clip_builder.py
42 passed

（broader playback batch 247 passed；test_video_sync 1 failed 與 test_song_use_left_ltc 2 failed 均在 base commit 已 fail，與本任務無關）
```

新 tests 全部 deterministic（gated events；唯一 bounded wait 是必然 state wait，無 wall-clock 斷言）。實引擎最壞情況（rapid edit 在 worker 啟動前）：started=2 / cancelled=1 / completed=1、cache 完整重建。

## Remaining issues

- 仍需真實 Windows 硬體 PERF A/B（`CUEPLAYER_PERF=1`）：cache ready vs builder active 的 `audio.callback.*` 對照 + 新增 builder metrics。
- 若 spike 仍超 budget：向量化的 `generate_ltc_pcm` 或 builder loop 定期 GIL yield（減總工作）。
- Timeline B2.2 仍 scope 外。

## Suggested next task

執行 focused Windows 硬體 PERF A/B 驗證；若仍有 severe stall 才進入下一個 Clips-only diagnostic。
