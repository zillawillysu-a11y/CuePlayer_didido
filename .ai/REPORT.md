# Timing Hardening Phase B2.1 — Regression Diagnostic + Performance Observability

## Task objective

診斷 B2 是否造成 GUI scheduling regression，並恢復可見的 Performance Report 與 B2 strip observability；不改 Playback/Audio/LTC/MTC/video decode 或 Zoom/Mark rendering architecture。

## What was implemented

- 比較 `0687e22..80d6a04`：B2 diff 僅涉及 `TimelineWidget`、測試與 AI 文件；`audio_engine.py`、`main_window.py` position fan-out 沒有 B2 diff。Main UI TC 在 Windows title-bar modal loop 停住仍是既有 GUI presentation 限制，不是新的 Audio/LTC/MTC clock regression。
- 確認 `Tools → Write Performance Report…` writer/action 仍存在；action 僅在程式啟動前 `CUEPLAYER_PERF=1` 時建立。現在保存 action reference，並以 UI test 確認可見及 trigger wiring。
- 延用既有 perf framework，補上 strip callback count、callback gap、pending work（只能為 0/1）及 stale discard counters；現有 strip/commit/Mark layer spans 保留。
- 新增 incremental pending-strip widget destruction regression test；既有 MTC GUI-stall-independence test 保持 PASS。

## Files changed

- `src/cueplayer/ui/timeline_widget.py`
- `src/cueplayer/ui/main_window.py`
- `tests/ui/test_performance_report_observability.py`
- `tests/ui/test_timeline_backdrop_deferred_rebuild.py`

## Architecture decisions

- 未新增 profiler；所有 measurement 使用 `cueplayer.diagnostics.perf`，PERF disabled 時為 no-op。
- B2 的 `singleShot(0)` strip callback 確實是 `strip → start(0) → strip` chain，但每次最多只有一個 pending timer，不會累積 queue；native modal loop 中不會產生 timer callbacks，因此沒有 pending backlog/burst。modal loop 結束後最多恢復一個 strip。
- zero-delay chain 仍可能在一般 GUI event loop 中消耗大量 callback turns；現以 `incremental_callback_gap_ms`、`incremental_strip_ms`、`incremental_commit_ms` 與 `ui.event_loop_long_task_ms` 實測判定，未宣稱已排除 starvation。

## Tests performed

```text
QT_QPA_PLATFORM=offscreen pytest -q tests/ui/test_performance_report_observability.py tests/ui/test_timeline_backdrop_deferred_rebuild.py tests/playback/test_mtc_gui_stall_independence.py
11 passed
```

## Remaining issues

- Zoom/Mark 實機仍卡頓有程式碼證據：Zoom strip 的 final commit 仍同步畫全部 ruler/LTC/Marks/sprites；Mark annotation rebuild 仍同步 `QPixmap(spatial)` + 全量 Mark/sprite pass。這不是本 diagnostic phase 要重寫的架構。
- 使用者找不到 report 的原因是未以 `CUEPLAYER_PERF=1` 啟動，action 依既有設計不會顯示。log 預設為 `%LOCALAPPDATA%\CuePlayer\cueplayer_perf.log`。

## Suggested next task

先以 `CUEPLAYER_PERF=1` 實機蒐集 Zoom、Mark、title-bar hold/release 的最後 manual dump，依 `incremental_callback_gap_ms`、strip/commit/Mark max、pending/stale counts 判斷是否需要一個明確範圍的 B2.2 render fix；不要直接開始 Phase C。
