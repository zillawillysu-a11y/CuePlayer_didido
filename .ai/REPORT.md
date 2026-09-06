# LTC Generator Clips — Phase 1 (domain + time mapping + persistence)
Date: 2026-09-06. Branch: technical-audit-0815-028d.
Upstream: origin/cursor/technical-audit-0815-028d.
Status: complete (Phase 1 only; no playback/UI/exporter changes made).

## Task objective
User-confirmed spec (2026-09-06): per-song LTC source modes are mutually
exclusive — `striped_file`, `full_track_generator`, `clip_generator`,
`off`. In `clip_generator`, generated LTC is emitted only inside user
LTC Generator Clips. Phase 1 (this task) = domain model, time mapping,
persistence/schema migration, tests. ASIO work parked per user (recent
Focusrite ASIO test clean; no clock correction).

## What changed
- `src/cueplayer/domain/models.py`
  - `SCHEMA_VERSION` 2 → 3.
  - `SongLtcSourceMode` literal + `coerce_song_ltc_source_mode()`; legacy
    default `"auto"` keeps pre-clip behavior (resolved from project
    `AudioOutputSettings`).
  - New `LtcClip` dataclass: `id`, `timeline_start_seconds`,
    `duration_seconds`, `start_timecode` (+ `end_seconds`, `create()`,
    `copy_with_new_id()`).
  - `Song.ltc_source_mode: str = "auto"`, `Song.ltc_clips: list[LtcClip]`;
    `Song.duplicate()` copies both (fresh clip ids).
- `src/cueplayer/domain/ltc_clips.py` (new, domain-only)
  - `clip_at_position(clips, pos)` — clip covers `[start, end]` at its exact
    end point, `[start, end)` otherwise; at a shared boundary the later
    clip wins.
  - `ltc_timecode_at(clips, fps, pos)` → `Timecode | None`; inside a clip
    `output_tc = clip.start_timecode + (pos - clip.timeline_start)` with the
    same nearest-frame rounding as legacy `absolute_timecode`.
  - `ltc_clip_tc_range(clip, fps)` — absolute TC range (end exclusive).
  - `validate_ltc_clips(clips, fps, song_duration)` → `(errors, warnings)`:
    errors = start < 0 / end > song end / duration ≤ 0 / bad TC; warnings =
    overlapping timeline ranges, overlapping or backwards TC ranges.
  - `add_ltc_clip(song, …)` — appends, keeps sorted, forces mode
    `clip_generator` (stops full-track generator; striped can't coexist).
  - `remove_ltc_clip(song, clip_id)` — never auto-restores
    `full_track_generator`; last-clip removal keeps `clip_generator`.
  - `resolved_song_ltc_source_mode(song, project_ltc_source, ltc_enabled)` —
    explicit modes win; `auto` → full_track_generator / striped_file / off
    mirroring today's project-level behavior.
- `src/cueplayer/persistence/project_store.py` — serialize/load
  `ltc_source_mode` + `ltc_clips` (missing clip ids get uuids).
- `src/cueplayer/persistence/project_migrations.py` — `_migrate_v2_to_v3`
  (defaults `auto` / `[]`; structurally sanitizes hand-written clips).
- Tests: new `tests/domain/test_ltc_clips.py` (21),
  `tests/persistence/test_ltc_clips_schema.py` (5); stale
  `SCHEMA_VERSION == 2` assertions updated in
  `tests/persistence/test_schema.py`,
  `tests/persistence/test_song_variants.py`,
  `tests/unicode/test_chinese_paths.py`.

## Design decisions
- `auto` retained as per-song default so existing projects are unchanged;
  the four user states are the explicit ones.
- Boundary: exact clip end still yields that clip's final TC; shared
  start/end boundary belongs to the later clip.
- Removing the last clip keeps `clip_generator` (user manually re-enables
  the full-track generator if wanted).
- Clip frame math matches legacy MTC rounding (round to nearest frame).

## Tests performed
- All non-playback test dirs pass (679 in one run; domain/persistence/
  unicode/exporters/media green individually).
- `tests/playback`: 174 passed; two PRE-EXISTING failures reproduced on
  clean HEAD via `git stash -u`:
  `test_ndi_probe.py::test_ensure_ndi_runtime_search_path_adds_dll_dir`
  (real NDI Tools install on this machine leaks env vars) and
  `test_song_use_left_ltc.py::test_file_ltc_right_strips_right_from_music`.
- Pre-existing hard crash when running the whole suite in one process also
  reproduced on clean HEAD.

## Remaining issues
None for Phase 1.

## Suggested next task (Phase 2, per user spec)
1. Playback wiring: AudioEngine emits generated LTC only inside clips
   (cache key + realtime cursor follow the clip table); MTC silent outside
   clips; UI timecode clock shows No TC / `--:--:--:--`.
2. UI: create/edit LTC Generator Clips; first clip switches the song to
   `clip_generator`; surface validation errors/warnings.
3. Exporter: `clip_generator` plans — Timecode Events only for marks inside
   clips; out-of-clip marks keep their Sequence Cue and are listed in
   export warnings; single MA Timecode object (no per-clip objects);
   overlapping/backwards TC ranges warned.
See `.ai/handoffs/2026-09-06_LtcClipsDomainPhase1.md`.
