# Timing Hardening Phase B2.1 — Regression Diagnostic + Performance Observability

## Task objective

確認 B2 是否使 GUI scheduling 變差，並恢復/驗證 Performance Report observability；不實作 Phase C 或改動播放架構。

## What was implemented

- 比較 `0687e22..80d6a04`：沒有 `audio_engine.py` 或 `main_window.py` position fan-out diff。title-bar TC freeze 是既有 Windows/Qt GUI presentation freeze，非 B2 clock regression。
- 確認 writer/action 均存在；action 僅在 launch-time `CUEPLAYER_PERF=1` 時建立，使用者未見是 feature gate 所致。
- B2 perf 新增/確認 callback count、callback gap、pending work（0/1）、stale discard、strip/commit/Mark layer spans。
- 加入 PERF action visibility/trigger/report-key test 與 incremental-close test。

## Files changed

- `src/cueplayer/ui/timeline_widget.py`
- `src/cueplayer/ui/main_window.py`
- `tests/ui/test_performance_report_observability.py`
- `tests/ui/test_timeline_backdrop_deferred_rebuild.py`
- `.ai/REPORT.md`、`.ai/NEXT_TASK.md`、本 handoff。

## Architecture decisions

- 沿用 `diagnostics.perf`；PERF disabled 無測量成本。
- strip 是 zero-delay chained callback，但 single-shot 保證同時只有一個 pending callback；modal loop 期間沒有 callback 累積，release 後最多一個恢復，不會 burst。
- 是否在一般操作中加重 GUI busy 不能靠靜態保證，改由新增 metrics 實測。

## Tests performed

```text
QT_QPA_PLATFORM=offscreen pytest -q tests/ui/test_performance_report_observability.py tests/ui/test_timeline_backdrop_deferred_rebuild.py tests/playback/test_mtc_gui_stall_independence.py
11 passed
```

## Remaining issues

- Zoom commit 與 Mark annotation pass 仍有同步 GUI work，是目前實機 Zoom/Mark stall 的直接候選；本 phase 不重寫 rendering。
- 需真實 Windows show dump，不能以 offscreen synthetic timing 判定 callback fairness。

## Suggested next task

先蒐集 PERF manual dump，再決定是否做 B2.2 render fix；不要直接進 Phase C。
