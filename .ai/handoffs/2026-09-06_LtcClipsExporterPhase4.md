# LTC Generator Clips — Phase 4 MA2 / MA3 Exporter

Date: 2026-09-06. Branch: `technical-audit-0815-028d`. Baseline: `e54ecf2`. Status: complete.

## Task objective

完成 MA2／MA3 對 `clip_generator` 的逐 Clip mapping，並維持既有 exporter invariants。

## What was implemented

- Export plan 分開保存原 timeline time、mapped MA event time 與 event membership。
- `clip_generator` 只重用 `clip_at_position()`／`ltc_timecode_at()`；clip 外 Main Mark 仍輸出 Sequence Cue。
- 絕對 mapped event TC 寫入同一 Song object，offset 為 0；多 Clip 不拆 object。
- MA2 direct/full-show Plugin XML 與 MA3 XML 共用 plan mapping。
- 重用 `validate_ltc_clips()`，補 pairwise backward／overlap 與 duplicate event warnings；warnings 不阻擋或改值。
- Show Patch／legacy Export Dialog 與 allocation TXT 顯示同一 warning list。
- 新增 MA2／MA3 deterministic fixtures。

## Files changed

- `src/cueplayer/exporters/common.py`, `plan_from_song.py`, `ma2/exporter.py`, `ma3/exporter.py`
- `src/cueplayer/ui/export_dialog.py`, `show_patch_page.py`
- `tests/exporters/test_ltc_clip_generator_export.py`
- `fixtures/ma2/clip_generator_timecode.xml`, `fixtures/ma3/clip_generator_timecode.xml`
- `.ai/REPORT.md`, `.ai/NEXT_TASK.md`, `AGENTS.md`

## Architecture decisions

1. Domain helper 是唯一 mapping formula source。
2. Legacy defaults 仍走原 event math 與 start offset。
3. Sequence Cue 與 Timecode Event membership 分離。
4. 絕對 event TC + zero object offset 維持一 Song 一 object。
5. Plan warning list 是 exporter report 的 single source。

## Tests performed

- Exporter suite：**132 passed**。
- Exporter + LTC domain：**153 passed**。
- Phase 4 targeted：**6 passed**。
- Full-show/timecode-only combined batch：**60 passed, 4 pre-existing offscreen UI failures**。
- `git diff --check`: passed。

## Remaining issues

- 目前 Windows offscreen Qt fonts 缺失下，3 個 preflight UI cases 與 1 個 row-color case 看到空 ShowPatch queue；單獨重跑仍重現，與本次 mapping 無關。
- 既有 carry-over 詳見 `.ai/REPORT.md`。

## Suggested next task

Reset audio callback continuity diagnostic counters when opening a new output stream, with a narrow playback regression test. Do not start it automatically.
