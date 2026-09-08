# Timeline UI hardening: initial clip_generator lane hydration + zoom font-weight leak

Date: 2026-09-07. Branch: `technical-audit-0815-028d`. Baseline: `758068a`. Status: complete.

## Task objective

Fix two remaining manual-test issues on top of the prior zoom-rendering hardening task
(LTC clip text stretch + Mark false-selection ring — already fixed, not touched here):

1. **Problem A** — a Song persisted with `ltc_source_mode = clip_generator` loses its
   LTC Clips lane on first load after reopening the project; the lane only reappears
   after the user manually toggles the Source menu away from and back to Clip Generator.
2. **Problem B** — track/lane header labels ("Video", "LTC Clips", Mark lane names)
   visibly go bold during a continuous mouse-wheel zoom gesture, reverting once the wheel
   stops.

No LTC domain mapping, playback, MTC, MA exporter, persistence format, AudioEngine, mark
timing, video sync, or NDI code was touched.

## What was implemented

### Problem A — root cause

`TimelineWidget` never resolves its own LTC source mode; it only stores whatever
`set_ltc_source_mode(mode)` last pushed into it (`TimelineWidget._ltc_source_mode`,
default `"off"`). The resolved mode (`resolved_song_ltc_source_mode`, domain function in
`ltc_clips.py`) is computed and pushed by MainWindow's `_push_ltc_mode_to_timeline()`.

That push was wired only into the **audio-load completion path**
(`_apply_loaded_audio`, called after `_apply_probed_audio_duration` / `_load_audio_path`
finish, or from the RAM-cache hit branch of `_prepare_waveform_and_audio`). Two other
song-hydration paths never called it at all:

- `MainWindow.__init__`'s direct `self.timeline.set_song(self.current_song)` at
  construction time (used for both a fresh window and — via `_try_restore_last_project`
  → `_open_project_path` → `_apply_project` → `_activate_song` — the very first song
  shown after reopening a saved project).
- `ShowSessionService.refresh_timeline()`, the function `activate_song_at` (every later
  song switch) calls to rebind the timeline.

For a Song with **no main audio file** (the common case for a Clip Generator-only song —
no stripe/file source needed), `_prepare_waveform_and_audio` takes the "no audio path"
branch, which calls `_schedule_video_music_standin()` and never reaches
`_apply_loaded_audio` — so `_push_ltc_mode_to_timeline()` never runs, and the
`TimelineWidget` is left on its constructor default (`"off"`), hiding the LTC Clips lane
regardless of what the Song's persisted `ltc_source_mode` says. A manual Source-menu
change works because that handler (`_on_ltc_source_mode_requested`) calls
`_push_ltc_mode_to_timeline()` directly.

### Problem A — fix

Made `ShowSessionService.refresh_timeline()` — the one function shared by MainWindow
construction and every later song activation — the single source of truth for this sync:
it now calls `h._push_ltc_mode_to_timeline()` right after `set_song`, synchronously,
independent of whether/when audio loads. `MainWindow.__init__`'s direct `set_song` call
gained the same `_push_ltc_mode_to_timeline()` call immediately after it, so first-paint
construction and every runtime song switch now go through the identical
set_song → apply_mark_line_settings → push_ltc_mode sequence. No fake signals, no
deferred timers.

`ShowHost` (the typed Protocol `ShowSessionService` depends on) gained a
`_push_ltc_mode_to_timeline()` method stub so the dependency stays explicit and
type-checked (`src/cueplayer/ports/show_host.py`).

Legacy `auto` resolution semantics (`resolved_song_ltc_source_mode`) were not touched.

### Problem B — root cause

`_paint_zoom_screen_annotations` (the function that repaints fixed-size overlays live,
every zoom-preview frame, on top of the stretched "spatial" raster) sets the shared
`QPainter`'s font to **bold** to draw Mark lane-glyph text — and never restored it
before returning (no `save()`/`restore()`, no reset to the original font). This function
runs only when the song has at least one Mark (`self._mark_annotation_sprites` non-empty).

Immediately after it returns (same `paintEvent` call, same `QPainter`), the dynamic
overlay pass runs `_paint_video_selection_live` and `_paint_ltc_selection_live`, which
each `drawText` a header sub-caption ("No clip selected" / clip name under "Video";
"No clip selected" / start-timecode under "LTC Clips") **without setting their own font
first** — they simply relied on the painter's ambient font staying whatever the widget's
default was. During a zoom gesture, that ambient font was left bold by the sprite pass
moments earlier in the same frame, so those captions rendered bold every zoom-preview
frame. Once the wheel stops, `_blit_zoom_preview` (and therefore
`_paint_zoom_screen_annotations`) is no longer called, so the leak stops occurring and
the captions revert to normal weight on the next paint — exactly matching the reported
"bold while zooming, normal once stopped" symptom.

This was confirmed by static code-flow analysis (painter font-state tracing across the
call chain), not by isolated review of the header 1:1-blit region (which is, as the
prior audit found, pixel-exact and not the actual defect) — the bold text was never
drawn *twice* misaligned as first suspected; it was a **single draw with a leaked font
weight**, which visually reads the same way (blurred/heavier glyph edges) at typical
viewing distance during rapid repaint.

### Problem B — fix

- `_paint_zoom_screen_annotations` now wraps its bold-font Mark-glyph block in
  `painter.save()` / `painter.restore()`, so the bold weight can never outlive this
  function call regardless of what runs after it in the same frame.
- Defense in depth: `_paint_video_selection_live` and `_paint_ltc_selection_live` now
  each explicitly `painter.setFont(self.font())` before drawing their header captions,
  instead of trusting the painter's ambient font state — closing the exact visible
  defect even if some other future code path leaves the font in a non-default state.

No font weights, renderer architecture, or paint order were otherwise changed; the
header 1:1 blit path from the prior audit is untouched.

## Files changed

- `src/cueplayer/application/show_session_service.py` — `refresh_timeline()` now pushes
  the resolved LTC mode.
- `src/cueplayer/ports/show_host.py` — added `_push_ltc_mode_to_timeline` to the
  `ShowHost` Protocol.
- `src/cueplayer/ui/main_window.py` — `__init__`'s first `timeline.set_song` call now
  followed by `_push_ltc_mode_to_timeline()`.
- `src/cueplayer/ui/timeline_widget.py` — `_paint_zoom_screen_annotations` font
  save/restore; `_paint_video_selection_live` / `_paint_ltc_selection_live` explicit
  font reset.
- `tests/ui/test_ltc_source_mode_initial_hydration.py` (new) — Problem A regression.
- `tests/ui/test_timeline_zoom_rendering_invariants.py` — added Problem B regression
  (`test_zoom_screen_annotations_do_not_leak_bold_font`).
- `tests/application/test_show_session_service.py`,
  `tests/ports/test_show_host.py` — updated host test doubles to implement the new
  `_push_ltc_mode_to_timeline` method (both were failing after the Problem A fix until
  updated).

## Architecture decisions

- Kept the fix inside the existing shared `refresh_timeline()` seam rather than adding a
  new signal/timer — the user explicitly required initial hydration and the runtime
  source-change path to use the same source-of-truth function; `refresh_timeline()`
  already was that seam for `set_song`, it just hadn't been made responsible for the LTC
  mode push yet.
- Fixed the font leak at its source (`save`/`restore`) rather than only patching the two
  call sites that happened to be affected today — any future live-overlay text added
  after `_paint_zoom_screen_annotations` in the same frame is now protected automatically.
  The two call-site resets are additional, not a substitute.

## Tests performed

All run with `QT_QPA_PLATFORM=offscreen`:

- `tests/ui/test_ltc_source_mode_initial_hydration.py` (new) — 5 passed.
- `tests/ui/test_timeline_zoom_rendering_invariants.py` — 4 passed (including the new
  font-leak regression).
- `tests/ui/test_ltc_clip_timeline.py`, `test_ltc_clip_dialog.py`,
  `test_ltc_waveform_track.py`, `test_bundle_ltc_remount.py`, `test_ltc_stale_badge.py`,
  `test_setlist_ltc_column_width.py`, `test_setlist_ltc_indicator.py`,
  `test_timeline_keep_zoom.py`, `test_timeline_zoom_overlay_resize.py`,
  `test_zoom_cue_video_state.py`, `test_zoom_waveform_geometry.py`,
  `test_waveform_high_zoom_outline.py` — 60 passed.
- `tests/domain/test_ltc_clips.py`, `tests/domain/test_ltc_clip_undo.py` — 26 passed.
- `tests/ui/test_song_edit_dialog.py` — 18 passed.
- `tests/application/test_show_session_service.py`, `tests/ports/test_show_host.py` —
  10 passed (2 pre-existing tests + the protocol conformance test needed the stub-host
  update above to keep passing after the Problem A fix).
- `git diff --check` — clean (only a pre-existing LF/CRLF autocrlf notice, no trailing
  whitespace/conflict markers).

Not run (per task scope / known issues, unchanged from prior handoff):
`tests/ui/test_cue_list_playhead_scroll.py` (known hang), Windows `video_sync` crash
test (`tests/playback/test_video_sync*.py`), and a full `tests/ui` sweep (142 files —
narrowed to the files above as directly relevant to this change).

## Remaining issues

None known for these two bugs. The prior task's parked items in `.ai/NEXT_TASK.md`
(physical loopback drift check, `test_song_use_left_ltc.py` routing assertions, NDI probe
test) are unrelated and untouched.

## Suggested next task

None queued — see `.ai/NEXT_TASK.md`. Await next manual-test findings.
