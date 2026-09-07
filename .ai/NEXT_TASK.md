# Next task

Timing Hardening Phase B2 已完成（2026-09-07）。詳見 `.ai/REPORT.md` 與 `.ai/handoffs/2026-09-07_TimingHardening_PhaseB2.md`。

先由使用者在真實 Windows show 驗證：播放時快速 Zoom 10–20 次、連續建立 Mark、Zoom + Mark 交錯、Mark Create/Move/Delete/Undo/Redo，以及 waveform/grid/Mark/Video Clip/LTC Clip 位置。確認 Audio、LTC、MTC 持續，UI TC/playhead 無明顯 freeze。

以 `CUEPLAYER_PERF=1` 啟動，Tools → Write Performance Report 讀取最後 manual dump；觀察 `timeline.backdrop.incremental_strip_ms`（單一 GUI strip）、`timeline.backdrop.incremental_commit_ms`、`timeline.mark_layer.rebuild_ms`、`ui.event_loop_long_task_ms`、`audio.callback.*`。`timeline.mark_backdrop.rebuild_ms` 是跨 Qt turns 的總 wall time，不是單次 blocking。

使用者明確要求後的下一候選 phase：**Timing Hardening Phase C — Clean Video Output title-bar freeze（Reason A only）**。不得處理 Qt presentation Reason B、Main UI title-bar、Art-Net、Ripple Edit、Insert Gap 或 Insert Time。

不要執行完整未過濾 `tests/ui/`，部分 fake `.mp4` 會啟動並卡住真實 waveform worker。
