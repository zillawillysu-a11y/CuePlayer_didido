# LTC Clip Remaining Playback Stall — Builder Diagnostic + Minimal Fix

## Task objective

診斷 LTC Clips 在 Windows 上「剩餘」playback stall 的第一個 Clips-only 根因：主要嫌疑是 callback 外的 async LTC clip PCM builder / cache builder（純 Python GIL / CPU pressure），即使 gap fast path 已啟用仍延遲 PortAudio callback。確認後施以最窄的安全修正。

## Findings（call-chain + benchmark）

Call chain：`set_song` / `play()` / `apply_audio_settings` / `refresh_song_ltc_routing` / buffer setup → `_ensure_clip_ltc_cache()` → 單一 `ThreadPoolExecutor`（`ltc-cache` worker）→ `generate_ltc_pcm()`（純 Python per-frame LTC 編碼）→ 全部 clips 完成後才一次性 publish `_ltc_clip_table` → callback 用 table slice；table 未完成時 fallback 在 callback 內建 `LtcPlaybackCursor`。

- Benchmark：`generate_ltc_pcm` ≈ **1.45 ms CPU / 每秒 clip**（48 kHz / 30 fps）；60 s clip ≈ 87 ms 連續 GIL 工作；30 min clip payload ≈ 數秒。
- 舊行為缺陷（本任務前）：
  1. **All-or-nothing publish**：任一 clip 沒完成前，callback 全程走 fallback。
  2. **無 cooperative cancellation**：invalidation 只清 table reference，in-flight worker 繼續把整包 build 做完。
  3. **可疊加 duplicate builds**：rapid edit（invalidation + 再 ensure）會 queue 第二個完整 build；舊 dedup 不考慮 generation，甚至會把「已被 invalidate 的 stale in-flight build」誤判為可重用而 suppress 掉真正需要的 rebuild（本任務中實際發現並修正）。
  4. Builder 沒有降 thread priority（其他背景 worker 都有）。
  5. 附帶發現：`clip_generator` 模式下 `detect_ltc_channel` 的檔案 stripe 自動掃描每次載入 stereo buffer 都會跑，但 clip 模式**根本不用**其結果——純浪費 CPU/GIL。
- A/B（本機實測，8 ms chunks、12×60 s clips ≈ 1 s GIL 工作）：
  - Builder active：mean 0.08–0.15 ms、p99 0.4–0.7 ms、**max ~2.2 ms spikes**（GIL contention）。
  - Builder idle（cache ready）：mean 0.003 ms、max 0.03 ms。
  - 結論：builder 不是 gap path 的阻塞點（gap 永不 wait builder），但它的持續 GIL/CPU 壓力確實造成 callback jitter spike；舊 all-or-nothing + stacking + 無 cancellation 會把壓力放大數倍。

## What was implemented

`src/cueplayer/playback/audio_engine.py`：

1. **Incremental per-clip publish**：`_ltc_clip_table` → `_ltc_clip_pcm` dict；每個 clip 完成立即 publish。Callback 對 ready clip 用 NumPy slice（`cache_hit`），pending clip 用 bounded O(chunk) fallback（`cache_miss`；cursor seek 是 O(1) `_skip_to_frame`，render 只 O(chunk)）。
2. **Callback 完全不碰 builder**：無 join、無 condition wait、無 future、無 filesystem/Qt/network/parse/unbounded loop。
3. **Duplicate suppression（generation-aware）**：只有「same key 且 same generation」的 in-flight build 會被 suppress；stale（generation 已 bump）的 in-flight job 不可重用，會由 successor 接棒。
4. **Cooperative cancellation**：`_invalidate_clip_ltc_cache()` bump `_ltc_clip_generation`；worker 在 clip 之間檢查 token，stale build 在下一個 clip 邊界停止（`builder_job_cancelled`）。
5. **Builder 降 thread priority**（`lower_background_thread_priority`，與其他背景 worker 同政策）；full-track `_ensure_ltc_cache` 也一併降。
6. **clip_generator 模式跳過檔案 LTC auto-detect scan**（`_refresh_ltc_detection` early return）。
7. **CUEPLAYER_PERF metrics**：`audio.ltc_clip.builder_job_started/completed/cancelled`、`builder_active_jobs`、`builder_duplicate_suppressed`、`builder_total_ms`、`builder_clip_ms`、`cache_rebuild_count`、`cache_hit`、`cache_miss`。

## Files changed

- `src/cueplayer/playback/audio_engine.py`
- `tests/playback/test_ltc_clip_playback.py`（改配合新 internals）
- `tests/playback/test_ltc_clip_builder.py`（新增，14 tests）
- `.ai/REPORT.md`、`.ai/NEXT_TASK.md`、本 handoff

## Architecture decisions

- Audio sample position 仍是唯一 playback clock；Playback Engine 仍是唯一 clock source。
- Builder lifecycle state（`_ltc_clip_inflight` / `_ltc_clip_generation` / `_ltc_clip_pcm`）只由 engine 內部使用；callback 只讀 immutable tuple 與 per-clip dict（GIL 下 tuple/dict 指派 atomic）。
- 未動 Timeline Zoom、Mark rendering、Main UI TC、Clean Video、MTC architecture、Art-Net、exporter、persistence schema、unrelated UI。
- 未改 `generate_ltc_pcm` / `LtcPlaybackCursor` 共享受眾（總工作量的根治屬後續 task）。

## Tests performed

```text
QT_QPA_PLATFORM=offscreen .venv\Scripts\python.exe -m pytest -q \
  tests/playback/test_ltc_clip_playback.py tests/playback/test_ltc_clip_builder.py
42 passed

（broader playback batch：247 passed；1 failed = test_video_sync duplicate-frame，base commit 已 fail）
（test_song_use_left_ltc 2 failed = base commit 已 fail，routing 相關，與本任務無關）
```

新 14 tests 全用 gated `threading.Event` fakes，deterministic；唯一 bounded wait 是「等到 gated builder 必然抵達 gate」的 state wait，無 wall-clock 斷言。涵蓋：single job submit、duplicate suppression、single builder / no stacking、stale result ignored、gap callback 絕不 wait builder、pending gap 仍靜音、pending active clip bounded fallback、mixed ready/pending、ready cache 用 cached PCM、A/B gap path 結構等價（有/無 builder）、invalidation scope、song switch cancellation、clip 模式跳過 detect scan。

實引擎最壞情況驗證（rapid edit 在 worker 啟動前發生）：`builder_job_started=2`、`builder_job_cancelled=1`、`builder_job_completed=1`、cache 完整重建（新時長 PCM）。

## Remaining issues

- 仍需真實 Windows 硬體 A/B：`CUEPLAYER_PERF=1`、`clip_generator` song、play/stop 與 clip edit 期間讀 builder metrics（`builder_active_jobs`、`builder_duplicate_suppressed`、`builder_total_ms`、`builder_clip_ms`）與 `audio.callback.*` 對照。
- 若 spike 仍超 budget：下一步是減少總工作——`generate_ltc_pcm` 向量化（NumPy/C）或在 builder loop 加定期 GIL yield；本任務刻意不碰共享受眾。
- Timeline B2.2 仍 scope 外。

## Suggested next task

執行 `.ai/NEXT_TASK.md`：focused Windows 硬體 PERF A/B 驗證（cache ready vs builder active），用新增 builder metrics 判定是否還有剩餘 Clips-only blocker。
