# Timing Hardening Phase B — Timeline Backdrop Rebuild

日期：2026-09-07。分支：`technical-audit-0815-028d`。

## Task objective

消除 Timeline Zoom 結束與建立／Drop Mark 時，scrub backdrop 同步 GUI-thread
raster rebuild 對 UI TC／playhead 造成的卡頓；不變更 Playback Engine、LTC 或 MTC。

## What was implemented

- `TimelineWidget` 加入 single-shot、0 ms Qt GUI-thread timer。invalidation 只記錄
  最新 reason/state；同一 event-loop turn 的連續 invalidation 只 rebuild 一次。
- Zoom idle 與 Mark revision 保留最後完整 cache，輸入／paint 路徑不再直接
  rasterize；callback 以最新 zoom、marks、clips、grid、waveform state rebuild，完成
  後 repaint。
- 換歌或影片 waveform 完成等其他 invalidation 維持既有立即清 cache，避免舊來源
  波形短暫顯示。
- direct seed／測試 helper rebuild 會取消 pending timer，防止第二次 bake。
- 新增 deferred scheduling、latest state、Mark 完成、widget 銷毀安全的回歸測試；
  既有 `MainWindow._add_mark()` 測試也確認最後 Mark cache 已完成。

## Files changed

- `src/cueplayer/ui/timeline_widget.py`
- `tests/ui/test_timeline_backdrop_deferred_rebuild.py`（新增）
- `tests/ui/test_mark_add_playback_perf.py`
- `tests/ui/test_zoom_cue_video_state.py`

## Architecture decisions

- `QPixmap`、`QPainter`、`TimelineWidget` 全部維持 GUI thread ownership；這是 Qt
  event-loop scheduling，不是 worker-thread handoff。
- AudioEngine sample clock、LTC、MTC 未修改；沒有新增 playback clock、sleep 或
  `QApplication.processEvents()`。
- 只在 Zoom／Mark 保留舊 cache，callback 讀取 live state，確保最後 invalidation
  不遺失；其他路徑不保留，避免 stale song/media。

## Tests performed

```text
QT_QPA_PLATFORM=offscreen pytest -q tests/ui/test_timeline_backdrop_deferred_rebuild.py tests/ui/test_zoom_cue_video_state.py tests/ui/test_mark_add_playback_perf.py tests/ui/test_timeline_pan_no_flash.py tests/ui/test_cached_timeline_poster.py tests/ui/test_video_waveform_backdrop_revision.py

40 passed
```

涵蓋 rapid invalidation coalescing、最後 zoom state、Mark drop 最終 rebuild、pending
callback 的 widget destruction、Zoom cache atomic presentation、Mark playback 與
既有 video waveform/cache。未跑完整 `tests/ui/`，避免 fake `.mp4` waveform worker hang。

## Remaining issues

- deferred final raster rebuild 仍有 GUI-thread 成本；它不在輸入或 paint call stack
  同步執行，且連續操作只做最新一次，但大型 show 仍需 Windows 手動驗證與
  `CUEPLAYER_PERF=1` 量測。
- Clean Video title-bar freeze（Phase C）與 Main UI title-bar cosmetic freeze 不在範圍。

## Suggested next task

等待使用者手動驗證本 Phase；僅在明確要求後開始 **Timing Hardening Phase C —
Clean Video Output title-bar freeze（Reason A only）**。不得自動開始，也不得處理
Reason B、Main UI title-bar、Art-Net、Ripple Edit 或 Insert Gap。
