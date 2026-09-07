# LTC Clip Playback Hot-Path Diagnostic + Minimal Fix

## Task objective

診斷並移除 LTC Clips-only callback 工作；即使 playhead 在所有 LTC clip 外，也不應造成 playback stall。

## What was implemented

- 原始路徑為 callback -> `_ltc_chunk()` -> `_clip_ltc_chunk()`；每個 callback（包含 gap）都 linear scan cached clips。PCM cache 未完成前還會 scan mutable `Song.ltc_clips`、parse start TC，並可能建立 temporary cursor。
- 新增 immutable precomputed frame intervals（sorted starts + prefix maximum ends）。callback binary-search；all-gap buffer 在任何 clip table scan、Song lookup、parse、cursor construction、LTC rendering 前直接回傳 silence。
- 一般 active clips 僅 slice candidate PCM ranges。crossing buffers 保留精確 half-open `[start, end)` silence/LTC portions；有效但 warning 的 overlap 保留既有保守行為。
- 新增 report metrics：`audio.ltc_clip.lookup_ms`、`generate_ms`、`gap_fast_path_count`、`active_path_count`、`clip_count`、`buffer_cross_boundary_count`（另有 max-ms）。

## Files changed

- `src/cueplayer/playback/audio_engine.py`
- `tests/playback/test_ltc_clip_playback.py`
- `.ai/REPORT.md`
- `.ai/NEXT_TASK.md`
- This handoff

## Architecture decisions

- 未修改 GUI、MTC、Art-Net、exporter、persistence 或 timeline。
- callback 未新增 diagnostics lock、I/O、Qt call、model mutation 或 extra lock。
- 既有 callback-wide AudioEngine lock 保持不變；本修正未延長它。
- Python-level LTC wave generation 僅在 async PCM publication 前的 active clip 發生，gap buffer 永不進入。

## Tests performed

```text
.venv\\Scripts\\python.exe -m pytest -q tests/playback/test_ltc_clip_playback.py tests/domain/test_ltc_clips.py tests/playback/test_audio_engine_source_ltc.py tests/playback/test_audio_engine_generator_stereo_music.py tests/playback/test_ltc_off_strips_from_music.py
55 passed

.venv\\Scripts\\python.exe -m compileall -q src/cueplayer/playback/audio_engine.py
git diff --check
```

## Remaining issues

- 仍需 hardware PERF verification。若 `gap_fast_path_count` 增加卻仍 deadline miss，調查第一個剩餘 Clips-only path，包含 callback 外 builder 的 GIL pressure。
- 獨立的 Timeline B2.2 GUI raster work 仍在 scope 外。

## Suggested next task

執行 `.ai/NEXT_TASK.md` 的 focused Windows LTC Clips gap/manual PERF reproduction。
