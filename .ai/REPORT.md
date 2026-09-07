# Timing Hardening Phase B2

## Task objective

消除 Zoom 與 Mark 單次 Timeline raster 對 GUI event loop 的阻塞，不改變 Playback、Audio/LTC/MTC 或影片解碼。

## What was implemented

- Mark revision 改為既有 spatial raster 的 annotation-only 重組；不再重畫 waveform、grid、background、Video/LTC lane。
- Zoom idle 改為 128px cooperative Qt timer strips；每個 GUI turn 只畫一個 strip，完整 generation 完成後 atomic swap。
- invalidation/direct rebuild 以 generation 取消 stale private target；只有最新 size/PPS/scroll 可以 commit。
- 延用 `CUEPLAYER_PERF=1`，增加 `timeline.mark_layer.rebuild_ms`、`timeline.backdrop.incremental_strip_ms`、`timeline.backdrop.incremental_commit_ms`。

## Files changed

- `src/cueplayer/ui/timeline_widget.py`
- `tests/ui/test_timeline_backdrop_deferred_rebuild.py`
- `tests/ui/test_zoom_cue_video_state.py`
- `tests/ui/test_cached_timeline_poster.py`

## Architecture decisions

- 拆分 expensive spatial raster 與 Mark annotation；playhead 保持 dynamic overlay。
- 沒有 background worker：QWidget/QPixmap/QPainter/font/device state 全在 GUI thread；以 cooperative strips 降低單次 blocking。
- AudioEngine sample clock、Audio output、LTC、MTC、Video decode 完全未修改。

## Tests performed

```text
QT_QPA_PLATFORM=offscreen pytest -q tests/ui/test_timeline_backdrop_deferred_rebuild.py tests/ui/test_zoom_cue_video_state.py tests/ui/test_mark_add_playback_perf.py tests/ui/test_timeline_pan_no_flash.py tests/ui/test_cached_timeline_poster.py tests/ui/test_video_waveform_backdrop_revision.py
42 passed
```

## Remaining issues

- Offscreen tests 是 synthetic；真實大型 show 必須以 `CUEPLAYER_PERF=1` 檢查 strip/commit/Mark layer max。`timeline.mark_backdrop.rebuild_ms` 現為跨多 turn 的總 wall time，不是單一 GUI blocking。
- Clean Video title-bar freeze、Main UI title-bar、Art-Net、Ripple Edit、Insert Gap 未處理。

## Suggested next task

先完成 B2 manual verification；之後由使用者明確決定下一 phase。候選仍是 Timing Hardening Phase C（Clean Video Output title-bar freeze，Reason A only）。
