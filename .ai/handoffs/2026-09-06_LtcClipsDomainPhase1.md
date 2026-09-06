# LTC Generator Clips — Phase 1 (domain + mapping + persistence)
Date: 2026-09-06. Branch: technical-audit-0815-028d.
Upstream: origin/cursor/technical-audit-0815-028d.
Status: complete (Phase 1 only; no playback/UI/exporter changes).

## Task objective
Per user spec (2026-09-06): a per-song LTC source mode with four mutually
exclusive states — `striped_file`, `full_track_generator`, `clip_generator`,
`off` — where `clip_generator` emits generated LTC only inside user-defined
LTC Generator Clips. Phase 1 = domain, time mapping, persistence/schema
migration, tests. ASIO capture work is parked (user confirmed the recent
Focusrite ASIO test showed no issues; no clock correction).

## User-confirmed spec (authoritative)
- Per-song modes are mutually exclusive. Creating the first clip switches the
  song to `clip_generator`, stops `full_track_generator`, and striped file
  LTC may not run alongside clips.
- Each clip stores `id`, `timeline_start_seconds`, `duration_seconds`,
  `start_timecode`.
- Inside a clip: `output_tc = clip.start_timecode +
  (timeline_position - clip.timeline_start_seconds)`.
- Outside every clip: no LTC, no MTC, UI shows No TC / `--:--:--:--`.
- Removing the last clip keeps `clip_generator` (or a manual switch to
  `off`); `full_track_generator` is never auto-restored.
- Exporter (later phase): `full_track_generator` keeps current math;
  `clip_generator` creates Timecode Events only for marks inside clips;
  marks outside clips still export their Sequence Cue but no Timecode
  Event, and are listed as warnings. No automatic multi MA Timecode objects
  per clip. Overlapping/backwards TC ranges must be validated + warned.

## What changed
- `src/cueplayer/domain/models.py`
  - `SCHEMA_VERSION` 2 → 3.
  - `SongLtcSourceMode` literal + `coerce_song_ltc_source_mode()`; the
    legacy default `auto` keeps pre-clip behavior (resolved from project
    `AudioOutputSettings`).
  - New `LtcClip` dataclass (`id`, `timeline_start_seconds`,
    `duration_seconds`, `start_timecode`; `end_seconds` property,
    `create()` / `copy_with_new_id()`).
  - `Song.ltc_source_mode: str = "auto"` and
    `Song.ltc_clips: list[LtcClip]`; `Song.duplicate()` copies both
    (clips get fresh ids).
- `src/cueplayer/domain/ltc_clips.py` (new, domain-only)
  - `clip_at_position(clips, pos)`: a clip covers `[start, end]` at its exact
    end point and `[start, end)` otherwise; at a shared boundary the
    later-starting clip wins.
  - `ltc_timecode_at(clips, fps, pos)` → `Timecode | None` (None outside
    clips). Frame offset uses `int(round(offset * fps))`, same rounding as
    the legacy `absolute_timecode` (MTC) path.
  - `ltc_clip_tc_range(clip, fps)` → absolute TC range (end exclusive).
  - `validate_ltc_clips(clips, fps, song_duration)` → `(errors, warnings)`:
    errors = start < 0, end > song end, duration ≤ 0, unparseable TC;
    warnings = overlapping timeline ranges, overlapping/backwards TC ranges.
  - `add_ltc_clip(song, …)`: appends, keeps clips sorted by start, and forces
    `ltc_source_mode = "clip_generator"` (mutual exclusion).
  - `remove_ltc_clip(song, clip_id)`: never auto-restores
    `full_track_generator`; last-clip removal keeps `clip_generator` (empty
    clip list ⇒ no TC emitted).
  - `resolved_song_ltc_source_mode(song, project_ltc_source, ltc_enabled)`:
    explicit modes win; `auto` → `full_track_generator` (project
    generator) / `striped_file` (auto or source side) / `off` (disabled).
- `src/cueplayer/persistence/project_store.py`
  - Serializes `ltc_source_mode` + `ltc_clips`; loader coerces mode and
    rebuilds `LtcClip` lists (missing ids get a uuid).
- `src/cueplayer/persistence/project_migrations.py`
  - `_migrate_v2_to_v3`: legacy songs get `ltc_source_mode="auto"`,
    `ltc_clips=[]`; hand-written clip entries are structurally sanitized
    (missing id filled, floats/strings coerced, non-dicts dropped).
- Tests
  - `tests/domain/test_ltc_clips.py` (new, 21 tests): inside/outside/boundary
    mapping, fps frame math, gap handling, validation errors/warnings
    (out-of-range, bad TC, timeline overlap, TC overlap, backwards TC),
    add/remove mode rules, legacy `auto` resolution.
  - `tests/persistence/test_ltc_clips_schema.py` (new, 5 tests): v2→v3
    migration defaults, migration sanitizing, save/load round-trip (Unicode
    project path), legacy v2 file loads with defaults, repository round-trip.
  - Updated stale `SCHEMA_VERSION == 2` assertions in
    `tests/persistence/test_schema.py`,
    `tests/persistence/test_song_variants.py`,
    `tests/unicode/test_chinese_paths.py` (now use the `SCHEMA_VERSION`
    constant).

## Design decisions
- `auto` is kept as the per-song default (5th value) so existing projects
  behave exactly as today; the four user states are the explicit ones.
- Boundary semantics: a position exactly at a clip's end still maps to that
  clip's final TC (matches the legacy single-clip end behavior); a position
  exactly at a start/end shared by two clips belongs to the later clip.
- Removing the last clip keeps `clip_generator` (no silent auto-revert); the
  user manually re-enables `full_track_generator` if wanted.
- Rounding matches the existing MTC `absolute_timecode` (round to nearest
  frame), so clip mapping and legacy full-track mapping agree at equal
  offsets.

## Tests performed
- `pytest tests/domain tests/persistence tests/unicode tests/exporters
  tests/media tests/application tests/core tests/diagnostics tests/repository
  tests/routing tests/timecode tests/util tests/web_remote` → all pass
  (679 passed across the non-playback dirs in one run; domain/persistence/
  unicode green individually).
- `pytest tests/playback` → 174 passed with two PRE-EXISTING failures also
  present on clean HEAD (verified via `git stash -u`):
  `test_ndi_probe.py::test_ensure_ndi_runtime_search_path_adds_dll_dir`
  (machine has a real NDI Tools install, env vars leak into the test) and
  `test_song_use_left_ltc.py::test_file_ltc_right_strips_right_from_music`
  (fails on clean tree too).
- A hard crash when running the entire suite in a single process is also
  pre-existing (reproduced on clean HEAD).

## Remaining issues / next phase
Phase 2 (per user spec, not yet started):
1. Playback wiring: AudioEngine emits generated LTC only inside clips
   (cache key + realtime cursor must follow the clip table), MTC silent
   outside clips, UI timecode clock shows No TC / `--:--:--:--`.
2. UI: LTC Generator Clip creation/editing (timeline or dialog); creating
   the first clip switches the song mode; validation warnings surfaced.
3. Exporter: `clip_generator` plans — Timecode Events only for in-clip
   marks; out-of-clip marks keep their Sequence Cue + export warning list;
   single MA Timecode object (no per-clip objects); overlapping/backwards
   TC ranges warned.
4. Optional later: per-clip FPS if ever requested (v1 keeps song FPS).
