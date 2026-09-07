# Next task

Timing Hardening Phase B2.1 已完成（2026-09-07）。詳見 `.ai/REPORT.md` 與 `.ai/handoffs/2026-09-07_TimingHardening_PhaseB2_1_RegressionDiagnostic.md`。

下一步先以 `CUEPLAYER_PERF=1` **在程式啟動前**啟動 CuePlayer；確認 `Tools → Write Performance Report…` 可見。播放真實 show 後分別執行快速 Zoom、連續 Mark、標題列按住/拖曳並 release，按 action 後讀 `%LOCALAPPDATA%\CuePlayer\cueplayer_perf.log` 最後一段 `manual-dump`。

重點：`timeline.backdrop.incremental_strip_ms`、`timeline.backdrop.incremental_callback_gap_ms`、`timeline.backdrop.incremental_commit_ms`、`timeline.mark_layer.rebuild_ms`、`timeline.backdrop.incremental_callback_count`、`timeline.backdrop.incremental_pending_work`、`timeline.backdrop.incremental_stale_discard`、`ui.event_loop_long_task_ms`、`audio.callback.*`。

收到實機 dump 後，再明確決定是否做 B2.2 render fix。不要直接開始 Phase C，也不要改 Playback Engine、Audio clock、LTC、MTC、video decode、Clean Video architecture、Art-Net、Ripple Edit 或 Insert Gap。

不要執行完整未過濾 `tests/ui/`，部分 fake `.mp4` 會啟動並卡住真實 waveform worker。
