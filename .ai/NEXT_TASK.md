# Next task

**Status:** Blocked — awaiting reference files from Willy, then real-hardware verification
**Type:** Feature (MA3 exporter — Song View / View Layout editor)
**Updated:** 2026-08-09

## Newest item (2026-08-09, do this first)

See `.ai/handoffs/2026-08-09_MA3SongViewAndViewLayoutEditor.md` for full
detail. Short version:

1. **Blocked on Willy:** get two real onPC View exports (same method as
   the earlier `SONGVIEW.xml`) — one containing his real **Effects/"All"
   Pool** widget, one containing a **Macros Pool** widget (only if he
   actually places one in his View). Add their shapes to
   `_MA3_POOL_WIDGET_SHAPES` in `src/cueplayer/exporters/ma3/exporter.py`
   — follow the exact pattern already used there for `sequence`/`groups`.
2. **Real-hardware verification round** (nothing from this session has
   been tested on his console yet except the `userprofiles/views` path
   fix and the cue-naming non-bug):
   - Export a show with a Sequence+Groups View Layout via the editor;
     confirm the widgets land at the right position/size on his 18×10
     screen (grid math: MA3 raw X/Y/W/H = grid units × 2, derived from
     `SONGVIEW.xml`, not yet re-confirmed through the editor path).
   - Confirm the trimmed install macro (redundant Label/Set-Property
     commands removed) still does everything the old one did — no
     regressions from the cleanup.
   - Confirm Sequence Pool now reserves a fixed per-song block (matches
     MA2) instead of packing tightly.
   - Confirm Effect/Group Pool Start + Slots Per Song fields are now
     editable for MA3 and actually affect the exported pool numbers.
   - Confirm ViewButton actually switches the View when Page Change runs.
3. Once (1) and (2) both check out: **commit + push this round's work**
   (everything is still uncommitted working-tree changes — see git
   status) with an updated report, and consider the MA3 Song Change
   Workflow feature (Song List + macros + View/ViewButton) fully closed
   out end-to-end.

## Also pending (not blocking)

- `.codex-test-tmp/`, `.tt-p1/`, `.tt-p2/`, `startup_error.txt` are
  untracked scratch files from manual verification during this session —
  safe to delete, not part of the feature, not committed.
- The pre-existing full `tests/ui` pytest suite crashes with `Windows
  fatal exception: stack overflow` partway through when run all together
  in one process (confirmed unrelated to recent changes). Run narrower
  paths: `tests/exporters tests/ui/test_show_patch_ma2_discovery.py`.
- `tests/ui/test_ma_preflight_export_integration.py` has 3 pre-existing
  failures unrelated to this round (confirmed via `git stash` — same 3
  failures with or without this session's changes).

## Explicitly not touched this round (per instruction)

- MA2 export semantics — untouched except reusing already-existing MA2
  settings fields for MA3 (the established pattern for this whole
  feature).
- video-waveform code — out of scope, not touched.
