# Timing Hardening Phase B2

## Task objective

降低播放中 Zoom/Mark 的單次 Timeline GUI raster stall，保持 AudioEngine、LTC/MTC 與 video decode 不變。

## What was implemented

- Mark create/delete/move/Undo/Redo 只重組 annotation，不再 invalid waveform/grid/static lane raster。
- Zoom idle static raster 改成 128px cooperative GUI strips，完成後 atomic swap。
- generation、PPS、scroll、size 檢查確保 stale render 永不覆蓋最新 Zoom。
- 新增 Mark layer、incremental strip、incremental commit perf counters。

## Files changed

- `src/cueplayer/ui/timeline_widget.py`
- `tests/ui/test_timeline_backdrop_deferred_rebuild.py`
- `tests/ui/test_zoom_cue_video_state.py`
- `tests/ui/test_cached_timeline_poster.py`
- `.ai/REPORT.md`、`.ai/NEXT_TASK.md`、本 handoff。

## Architecture decisions

- static/dynamic split：Marks 為 annotation-only layer；playhead 維持 dynamic。
- 無 background work；所有 Qt GUI-owned objects 都維持 GUI thread，使用 Qt cooperative scheduling。
- Playback、AudioEngine、LTC、MTC、video decode 均未修改。

## Tests performed

```text
QT_QPA_PLATFORM=offscreen pytest -q tests/ui/test_timeline_backdrop_deferred_rebuild.py tests/ui/test_zoom_cue_video_state.py tests/ui/test_mark_add_playback_perf.py tests/ui/test_timeline_pan_no_flash.py tests/ui/test_cached_timeline_poster.py tests/ui/test_video_waveform_backdrop_revision.py
42 passed
```

## Remaining issues

- synthetic offscreen 測試無法代表 Windows 真實 show；請以 `CUEPLAYER_PERF=1` 量測 `incremental_strip_ms`、`incremental_commit_ms`、`mark_layer.rebuild_ms`。
- annotation commit 仍是 GUI work，但不含 full waveform/grid bake。

## Suggested next task

等待 B2 manual verification；下一候選為 Timing Hardening Phase C（Clean Video Output title-bar freeze，Reason A only），不可自動開始。
