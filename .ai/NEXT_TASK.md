# Next task

## Focused LTC Clips 硬體 PERF A/B 驗證（2026-09-07）

Builder diagnostic + minimal fix 已完成（incremental publish、duplicate suppression、cooperative cancellation、priority lowering、detect-scan skip）。Windows 上以 `CUEPLAYER_PERF=1` 啟動 CuePlayer，載入多個 LTC clips 的 `clip_generator` Song（總長 ≥ 5 min），執行兩種 run 並用 **Tools -> Write Performance Report** 只讀最新 manual dump：

1. **Builder-active run**：play 開始後 2 秒內（builder 還在 build）持續播放 ≥ 15 s，並做一次 clip edit（duration 改動）觀察 cancellation。
2. **Builder-idle run**：cache 完成後同樣播放 ≥ 15 s。

必要 evidence（A/B 對照）：

- `audio.ltc_clip.builder_active_jobs` 在 active run 期間為 1、idle run 為 0。
- active run 的 `audio.ltc_clip.cache_miss` 只發生在 builder 尚未 publish 的 clips；idle run 應為 0（全 `cache_hit`）。
- clip edit 後 `builder_job_cancelled` +1 且 `builder_duplicate_suppressed` 不因 rapid edit 疊加（無第二個 stale full build 跑到完成）。
- 兩 run 的 `audio.callback.exec_max_s`、`deadline_miss_count`、`output_underflow_count` 對照：idle run 應明顯乾淨；active run 若有超 budget spike，記錄 `builder_clip_ms.max_ms` 是否對齊。
- gap 期間 `audio.ltc_clip.gap_fast_path_count` 持續增加、`active_path_count` 不變（callback 不碰 builder 的結構保證在硬體上成立）。

判定：

- 若 idle run 乾淨、active run 的 spike 幅度 ≤ 單一 `builder_clip_ms`（< 100 ms）且無 sustained underflow → 剩餘 stall 已解，結案，另行進入 Timeline B2.2。
- 若 active run 仍 severe stall → 下一 diagnostic：減少總工作（`generate_ltc_pcm` NumPy/C 向量化，或 builder loop 定期 GIL yield），不要先動 MTC / Timeline。

Pointers: `.ai/REPORT.md` and `.ai/handoffs/2026-09-07_LtcClipRemainingPlaybackStall.md`.
