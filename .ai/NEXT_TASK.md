# Next task

## Focused LTC Clips hardware verification（2026-09-07）

LTC Clip Playback Hot-Path fix 已完成。Windows 上以 `CUEPLAYER_PERF=1` 啟動 CuePlayer，載入有多個 LTC clips 的 `clip_generator` Song，並在 playhead 保持於 gap 時播放至少 15 秒。使用 **Tools -> Write Performance Report**，只讀最新 manual dump。

必要 evidence：

- gap 中 `audio.ltc_clip.gap_fast_path_count` 會增加。
- gap 中 `audio.ltc_clip.active_path_count` 不變；all-gap exercise 的 `audio.ltc_clip.generate_ms` 應為零或不存在。
- 對照 clip-active run、no-LTC run 的 `audio.callback.exec_max_s`、`deadline_miss_count`、`output_underflow_count`。
- 重複 gap-to-clip 與 clip-to-gap boundary，確認精確的 half-open `[start, end)` 行為。

若 gap counter 證明此路徑已使用後 severe stalls 仍存在，以新 metrics 診斷第一個剩餘 LTC-Clips-only blocker（包含 callback 外 async PCM builder）。該 diagnostic task 不要恢復 Timeline B2.2。

Pointers: `.ai/REPORT.md` and `.ai/handoffs/2026-09-07_LtcClipPlaybackHotPath.md`.
