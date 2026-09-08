# MA3 Song View + View Layout editor integration

**Date:** 2026-08-09
**Branch:** `cursor/video-wave-import-artifact-028d`
**PR:** (none yet — not pushed this round)

## Task objective

Continue the MA3 "Song Change Workflow" exporter (Song List Sequence +
fixed/song macros were already complete from a prior round). This round:
(1) add per-song **Song View** + **ViewButton** switching, first as a
fixed copy of a reference export, then — after Willy tested on real
hardware and asked for it — rewired onto the same interactive **View
Layout editor** MA2 already has; (2) fix several real-hardware bugs
Willy found while testing (wrong View library path, redundant/illegal
macro commands, Sequence Pool numbering not reserving a per-song block,
several Console Setup fields locked out for MA3 that should not have
been).

## What was implemented

**Song View + ViewButton (first pass, fixed copy):**
- `Ma3Exporter.write_song_view()` — new method, one `<View>` per song.
- Fixed macro list gained `Set Songviewbutton`
  (`SetGlobalVariable "songviewbutton" "<value>"`), and the existing
  `Page Change` macro's `Assign View $"song" At ViewButton 2.10`
  (hardcoded) became `Assign View $"song" At ViewButton
  $"songviewbutton"` (reads the variable — matches Willy's
  `VIEWBUTTON.xml` reference and MA2's already-working equivalent).
- `export_show_to_directory()` gained `include_song_views` /
  `view_pool_start` / `song_viewbutton` params, reusing the existing
  `ma2_include_song_views` / `ma2_view_pool_start` / `ma2_song_viewbutton`
  settings (same reuse pattern as every other MA3 setting so far).

**Bug: View files landed in the wrong library folder.** Real hardware
gave `Illegal object` on every `Import View Library` — Views are not a
`datapools/` subfolder like Sequences/Timecodes/Macros; they live under
`gma3_library/userprofiles/views` (confirmed by Willy directly on his
machine). Fixed `resolve_ma3_datapool_dirs()` to resolve `views_dir`
against `userprofiles/views`, a sibling of `datapools`, not inside it.
Re-tested — View import now succeeds.

**View Layout editor for MA3 (second pass, after Willy tested the fixed
copy and asked for the real thing):** Willy: *"接到MA2現有的View Layout編輯器，
不過有一些Pool的語法不一樣，比如說我的Effect Pool 就會是All的Pool"* — wire
MA3 into the *same* interactive View Layout editor MA2 uses (drag/resize
Pool windows on a fixed grid), not a separate MA3-only editor.
- Confirmed (via the math on Willy's real `SONGVIEW.xml` sample) that
  MA3's Screen grid is **18 columns × 10 rows**, and its raw
  `<ViewWidget>` X/Y/W/H are exactly **2× the grid-cell coordinates**
  (MA2's grid is 16×8, no such multiplier).
- `ui/ma2_view_layout.py`'s `Ma2ViewLayoutStage` (previously hardcoded to
  16×8 everywhere — paint grid, drag/resize clamping) now has
  `grid_w`/`grid_h` instance state and a `set_grid_size()` method;
  `GRID_SIZE_BY_CONSOLE = {"ma2": (16, 8), "ma3": (18, 10)}` added.
  `ShowPatchPage` calls `set_grid_size()` on project load and on
  MA2⇄MA3 console toggle. Pool Inspector X/Y/W/H spin ranges widened to
  the max of both grids (stage clamping enforces the real active limit).
- `Ma3Exporter.write_song_view()` rewritten to be **layout-driven**: it
  now takes the *same* `layout: list[dict]` shape the editor already
  produces (`{"type", "x", "y", "w", "h", ...}`), looks each entry's
  `type` up in a new `_MA3_POOL_WIDGET_SHAPES` table, and skips any
  entry whose type has no confirmed MA3 shape yet (never guesses).
  Populated so far: `sequence` (`WindowSequencePool`) and `groups`
  (`WindowGroupPool`) — both shapes taken directly from `SONGVIEW.xml`.
  `export_show_to_directory()` gained a `view_layout` param, wired at the
  UI call site to `project.ma_export.ma2_view_layout` (same expression
  MA2's own call site already uses).
- The View Layout **tab itself was never console-gated** — no UI-enable
  work was needed there beyond the grid-size sync.

**Console Setup fields wrongly locked for MA3:** Willy reported Sequence
Pool numbers "not jumping correctly" and being unable to type into
"Slot Per Song". Root cause #1 (real bug): MA3's Sequence Pool allocation
in `build_show_patch()` packed tightly (`seq += used_slots`) while MA2
reserved a fixed per-song block (`seq += max(used_slots,
ma2_sequence_slots_per_song)`) — Willy confirmed he wants MA3 to match
MA2's reserved-block behavior; fixed to apply the same formula for both
consoles. Root cause #2 (UI-only): `Sequence Slots Per Song`, `Effect
Pool Start/Slots`, `Group Pool Start/Slots` were still gated MA2-only in
`ShowPatchPage`'s enable/disable lists even though the underlying
allocation math in `show_patch.py` already applies to both consoles —
enabled for MA3 in both gating locations (`_load_settings_into_ui`,
`_on_console_toggled`).

**Also fixed this round (smaller, real-hardware-reported):**
- Removed several **redundant** macro commands that duplicated values
  already baked into the exported XML (`Label Sequence`/`Label
  Timecode`/10× `Set Timecode ... Property ...`) — cut a many-song
  show's install macro roughly in half. Two of the removed property
  tokens (`"Goto"`, `"Playback and Record"`) were unverified guesses real
  hardware rejected outright as `Illegal property` — dropping them loses
  nothing since `"Manual Events"` is MA3's own factory default.
  `Label Executor` for the Song List (also `Illegal object` on real
  hardware) removed the same way — its Name is already baked in the XML.
- MA3 Timecode name no longer gets a `_TC` suffix (bare name, matching
  the earlier `_Main` suffix fix for Sequences) — `Select Timecode
  $"song".` in Page Change needs an exact match.
- Confirmed (after a long real-hardware debugging thread) that the
  MA3 exporter's cue-naming code was correct all along — an earlier
  "Cue names missing" bug report turned out to be Willy testing/exporting
  a different song than the one he'd typed Notes into. No exporter change
  was needed for that thread besides re-adding a (harmless, likely
  belt-and-suspenders) `Appearance="Cue Point Main"` attribute to
  `_SEQUENCE_ATTRS` that was genuinely missing compared to the reference.

## Files changed

- `src/cueplayer/exporters/ma3/exporter.py` — `write_song_view` rewrite,
  `_MA3_POOL_WIDGET_SHAPES`, `MA3_VIEW_GRID_UNIT`, `resolve_ma3_datapool_dirs`
  4th return value (`views_dir`), redundant Label/Set-Property command
  removal, `Appearance` attribute, ViewButton macro wiring.
- `src/cueplayer/exporters/common.py` — removed the dead
  `ma3_timecode_set_property_commands()` (now redundant with baked XML).
- `src/cueplayer/exporters/show_patch.py` — Sequence Pool reserves a
  fixed per-song block for both consoles now (was MA2-only).
- `src/cueplayer/ui/ma2_view_layout.py` — `Ma2ViewLayoutStage` grid size
  parametrized (`grid_w`/`grid_h`/`set_grid_size`), `GRID_SIZE_BY_CONSOLE`.
- `src/cueplayer/ui/show_patch_page.py` — MA3 export call site gained
  `include_song_views`/`view_pool_start`/`song_viewbutton`/`view_layout`;
  Sequence/Effect/Group Pool Start+Slots fields enabled for MA3; grid-size
  sync on project load and console toggle; Pool Inspector spin ranges
  widened; View x/y/w/h clamping made grid-size-aware (was hardcoded 16/8
  in 3 places).
- `tests/exporters/test_ma3_song_workflow.py` (new-ish file, heavily
  extended this round) — View shape/grid-conversion tests, ViewButton
  macro tests, redundant-command-removal regression tests.
- `tests/exporters/test_generate_export.py`, `test_show_patch.py`,
  `test_ma_default_dirs.py` — updated for the `resolve_ma3_datapool_dirs`
  4-tuple, the Sequence-Pool-stride behavior change, and removed
  redundant-command assertions.

## Architecture decisions

- MA3's View Layout data model is the **same** `ma2_view_layout` list of
  dicts MA2 already uses — console-agnostic by design; only the grid
  size (16×8 vs 18×10) and the dict→XML shape mapping differ per console.
  No new settings fields were added for this.
- `_MA3_POOL_WIDGET_SHAPES` is deliberately a **partial** table (2 of 18
  Pool Types mapped). `write_song_view` silently skips unmapped types
  rather than guessing an XML shape with no reference — matches this
  whole exporter's established rule (never invent grandMA3 syntax without
  a real onPC reference or official docs to check it against).
- Sequence Pool allocation is now identical between MA2 and MA3
  (fixed per-song block, `ma2_sequence_slots_per_song`) — this was an
  explicit ask from Willy this round, not an assumption.

## Tests performed

`QT_QPA_PLATFORM=offscreen .venv/Scripts/python.exe -m pytest
tests/exporters tests/ui/test_show_patch_ma2_discovery.py -q` —
**168 passed** (repeated after every change in this round).

**Real-hardware confirmed by Willy this round:**
- View import succeeds after the `userprofiles/views` path fix.
- Cue naming was never actually broken (see above).

**NOT yet real-hardware confirmed this round** (code + offscreen tests
only):
- The View Layout editor → MA3 XML pipeline end-to-end (grid math is
  derived from `SONGVIEW.xml`'s numbers, not yet re-tested by exporting
  through the editor and importing on his console).
- The Sequence Pool per-song-block change.
- The Effect/Group Pool Start/Slots fields now being editable for MA3.
- The redundant-command removal (Label Sequence/Timecode, Set Timecode
  Property, Label Executor) — Willy's last real macro run was *before*
  this cleanup; needs one more real export+run to confirm the trimmed
  macro still does everything the old one did.

## Remaining issues

- **Blocking `_MA3_POOL_WIDGET_SHAPES` completion:** Willy still needs to
  send two real onPC View exports (same method as `SONGVIEW.xml`) — one
  containing his actual **Effects/"All" Pool** widget, one containing a
  **Macros Pool** widget (only if he actually places one in his View).
  Without these, `effects` and `macros` Pool Types remain selectable in
  the editor but silently produce no widget in the MA3 export.
- Nothing from this round (or the prior MA3 Song-List/macro round) is
  committed yet — see git status; all changes are still working-tree only.
- `.codex-test-tmp/`, `.tt-p1/`, `.tt-p2/`, `startup_error.txt` are
  untracked scratch directories/files from this session's manual
  verification scripts — not part of the feature, safe to ignore/delete,
  not committed.

## Suggested next task

1. Get Willy's two pending reference View exports (Effects/"All" Pool,
   Macros Pool) and complete `_MA3_POOL_WIDGET_SHAPES`.
2. Real-hardware round: export a show with a Sequence+Groups View Layout,
   confirm the widgets land in the right position/size on his 18×10
   screen, confirm the trimmed install macro still runs clean end-to-end
   (Import/Assign/Label, Sequence Pool block reservation, Effect/Group
   Pool fields), confirm ViewButton actually switches the View on
   Page Change.
3. Once (1)+(2) are both confirmed, commit + push this round's work
   (currently all uncommitted) with a proper handoff/report update, and
   consider closing out the MA3 Song Change Workflow feature as a whole
   (Song List + macros + View/ViewButton are then all real-hardware
   verified end-to-end).
