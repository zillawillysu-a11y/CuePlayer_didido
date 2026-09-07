# Next task

Timing Hardening Phase B — Timeline Backdrop Rebuild 已完成（2026-09-07）。詳見
`.ai/REPORT.md` 與 `.ai/handoffs/2026-09-07_TimingHardening_PhaseB.md`。

先等待使用者在真實 Windows show 完成：播放中快速 Zoom、連續建立 Mark、Zoom +
Mark 交錯、waveform/Mark/Video Clip/LTC Clip/grid 位置，以及 Mark Undo/Redo；確認
Audio、LTC、MTC 持續，UI TC/playhead 不再明顯停住。

使用者明確要求後的下一候選 phase：**Timing Hardening Phase C — Clean Video Output
title-bar freeze（Reason A only）**。僅可將 `video_sync.update_position()` 觸發從 GUI
`_poll` 解耦；不得處理 Qt presentation Reason B、Main UI title-bar、Art-Net、Ripple
Edit、Insert Gap 或 Insert Time。

其餘 parked tasks 與 baseline test 注意事項請看
`.ai/handoffs/2026-09-07_TimingArchitectureDiagnostic.md`。不要執行完整未過濾
`tests/ui/`，部分 fake `.mp4` 會啟動並卡住真實 waveform worker。
