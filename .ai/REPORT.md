# LTC Generator Clips — Phase 4 MA2 / MA3 Exporter

Date: 2026-09-06. Branch: `technical-audit-0815-028d`. Baseline: `e54ecf2`. Status: complete.

## Task objective

讓 MA2 與 MA3 exporter 支援 `clip_generator` 的逐 Clip Timecode mapping，同時保留既有 Sequence、full-track、full-show 與 timecode-only 行為。

## What was implemented

- `SongExportPlan` 分開保存 Mark timeline position 與實際 MA Timecode Event time；Main Cue 可明確略過 event，Button lane 有 filtered mapped event list。
- `build_export_plan()` 在 `clip_generator` 只透過 `clip_at_position()` 與 `ltc_timecode_at()` 映射。Clip 外 Main Mark 仍留在 Sequence，只省略 Timecode Event；Button 的既有 2-cue self-release sequence 不變。
- Clip events 以絕對 mapped TC 寫入同一 Song Timecode object，object offset 為 0，因此多個不連續或倒退的 Clip TC 仍是一 Song 一個 object。
- MA2 單曲 XML 與 full-show Plugin 內嵌 XML、MA3 XML 均使用 resolved plan；MA2 略過 event 後仍以原 Sequence store-order index 指向正確 Cue。
- 重用 `validate_ltc_clips()`，另做 pairwise backward／TC overlap 與 resulting event frame duplicate 檢查。全部只 warning，不阻擋、不重排、不改 TC、不拆 show。
- Warning 包含 Song、Clip／Mark、問題類型及相關 TC；Show Patch 完成訊息與 `Export_Allocation.txt`、舊 Export Dialog 預覽與完成訊息均會呈現。
- 新增 MA2／MA3 deterministic `clip_generator_timecode.xml` fixtures。

## Files changed

- `src/cueplayer/exporters/common.py`, `plan_from_song.py`, `ma2/exporter.py`, `ma3/exporter.py`
- `src/cueplayer/ui/export_dialog.py`, `show_patch_page.py`
- `tests/exporters/test_ltc_clip_generator_export.py`
- `fixtures/ma2/clip_generator_timecode.xml`, `fixtures/ma3/clip_generator_timecode.xml`
- `.ai/REPORT.md`, `.ai/handoffs/2026-09-06_LtcClipsExporterPhase4.md`, `.ai/NEXT_TASK.md`, `AGENTS.md`

## Architecture decisions

1. Mapping 留在 Song-to-plan adapter；MA2／MA3 不複製 domain formula。
2. Legacy plan defaults 保留原 mark time 與 song start offset math。
3. Sequence membership 與 Timecode event membership 分開，確保 clip 外 Mark 不丟 Cue。
4. 絕對 mapped event TC 加 zero object offset 支援不連續 mapping，同時維持一 Song 一 object。
5. Warning list 位於 plan，exporter summary 與 UI report 共用同一 deterministic source。

## Tests performed

- `tests/exporters`: **132 passed**。
- `tests/exporters` + `tests/domain/test_ltc_clips.py`: **153 passed**。
- Phase 4 targeted：**6 passed**，涵蓋 single/multi Clip、exact start/end、adjacent boundary、outside Sequence retention、單一 object、MA2 full-show embedded XML、backward/overlap/duplicate warnings、legacy modes。
- Full-show/timecode-only regression combined batch：**60 passed, 4 pre-existing offscreen UI failures**。
- `git diff --check`: passed。

## Remaining issues

- 既有 offscreen PySide6 問題：`test_ma_preflight_export_integration.py` 3 cases 與 `test_row_color_export.py` 1 case 在 Qt fonts directory 缺失時看到空 ShowPatch queue；單獨重跑仍重現，未經本次 mapping path。
- Carry-over：新 stream open 時 reset audio callback continuity counters；實體 loopback／長時間 drift；既有 NDI、routing、video-sync、font、WebRTC 與 Windows stack-overflow failures。

## Suggested next task

Reset audio callback continuity diagnostic counters when opening a new output stream, with a narrow playback regression test. Do not start it automatically.
