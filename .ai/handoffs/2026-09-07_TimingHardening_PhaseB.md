# Timing Hardening Phase B — Timeline Backdrop Rebuild

日期：2026-09-07。分支：`technical-audit-0815-028d`。

## Task objective

修正 Zoom 與建立／Drop Mark 同步觸發 scrub backdrop rebuild、starve Qt GUI event loop
並讓 UI TC/playhead 卡頓的問題。

## What was implemented

- 新增 zero-delay single-shot Qt timer；rapid invalidation 保留 latest reason，timer
  active 時不重啟，故一批操作只 rebuild 一次。
- Zoom idle 與 Mark revision 保留最後完整 cache，timer callback 以最新 widget state
  rebuild 並 atomic swap 後 repaint。
- song switch／video waveform 等其他 invalidation 保持清 cache，杜絕 stale source。
- direct rebuild 清除 pending request，避免 callback 第二次 rebuild。

## Files changed

- `src/cueplayer/ui/timeline_widget.py`
- `tests/ui/test_timeline_backdrop_deferred_rebuild.py`（新增）
- `tests/ui/test_mark_add_playback_perf.py`
- `tests/ui/test_zoom_cue_video_state.py`
- `.ai/REPORT.md`、`.ai/NEXT_TASK.md`、本 handoff。

## Architecture decisions

- 沒有 worker thread：`QWidget`、`QPixmap`、`QPainter` 均留在 GUI thread。
- 未修改 AudioEngine clock、LTC、MTC、video decode 或 playback architecture。
- 沒有 sleep、`QApplication.processEvents()` 或人工 delay。

## Tests performed

```text
QT_QPA_PLATFORM=offscreen pytest -q tests/ui/test_timeline_backdrop_deferred_rebuild.py tests/ui/test_zoom_cue_video_state.py tests/ui/test_mark_add_playback_perf.py tests/ui/test_timeline_pan_no_flash.py tests/ui/test_cached_timeline_poster.py tests/ui/test_video_waveform_backdrop_revision.py

40 passed
```

新測試覆蓋 coalescing、最後 zoom state、Mark rebuild、widget destroyed pending callback；
既有測試覆蓋 cache presentation、video waveform revision 與播放中加 Mark。

## Remaining issues

- final raster rebuild 仍有單次 GUI-thread 成本；此 Phase 只將它移出 input／paint
  call stack 並合併重複操作，沒有把 Qt raster API 移到不安全的 background thread。
- 需以真實 Windows show 與 `CUEPLAYER_PERF=1` 測量大型 project。
- Phase C 未開始。

## Suggested next task

先由使用者完成 Phase B 手動 checklist；只有明確要求後才開始 Timing Hardening
Phase C — Clean Video Output title-bar freeze（Reason A only）。
