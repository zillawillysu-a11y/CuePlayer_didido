# Song Variants — Domain & Persistence Design

**Status:** Sprint 5 Task 4 complete (Anchor Computation — draft only)  
**Updated:** 2026-08-03  
**Scope tip:** `cursor/sprint5-anchor-computation-028d`  
**Related:** [`roadmap.md`](roadmap.md) · [`PRODUCT_SPEC.md`](PRODUCT_SPEC.md) · [`architecture_overview.md`](architecture_overview.md) · [`current_architecture.md`](current_architecture.md)

**Sprint 5 Task 4 constraint:** Draft computation only. No Apply/persistence,
no playback changes, no Timeline redesign.

---

## 1. Goals (from Feature Task 1)

| Goal | Implication |
|------|-------------|
| One Song may contain multiple media **variants** | Explicit `SongVariant` list on `Song` |
| Cues stay on the **Song** | `marks` / mark lanes remain song-scoped; times on the song timeline |
| Playback uses **one selected variant** at a time | `selected_variant_id` + sole clock still loads one audio buffer |
| Future video / LTC / click on a variant | Variant owns a small media bag; start with audio only |
| Backward compatible projects | Schema migration; read old `audio_tracks`; transitional shims |

Non-goals for the first implementation slice: simultaneous multi-lane Reference paint, Align Anchors UI, overlay, auto cross-correlation, EventBus, UI redesign.

---

## 2. Audit — current Song domain

### 2.1 `Song` (as-built)

Owns (among other chrome fields):

| Field | Role today |
|-------|------------|
| `audio_tracks: list[AudioTrack]` | Intended multi-track list; **runtime treats as single main bed** |
| `video_clips` | Song-level VJ lane (shared timeline) |
| `marks` / `mark_lanes` | Song-level cues (must stay here) |
| `duration_seconds` | Song timeline length (often overwritten from loaded main audio) |
| `file_ltc_side` | Song-level file-LTC routing for the loaded music file |
| `music_volume` / `audio_gain_db` | Song-level music/waveform gain |
| `bpm` / `bpm_auto` | Song-level tempo (detect uses main audio path) |
| Timebase | `start_timecode`, `fps` |

### 2.2 `AudioTrack` (as-built)

```text
id, name, path, role ∈ {main, reference},
color, muted, solo, locked, hidden, offset_seconds
```

Already looks like a multi-track model, but **product code paths almost always resolve one path**:

- `_main_audio_path_for_song`: first `role == "main"`, else `audio_tracks[0]`
- Load / BPM / LTC / waveform / bundle / remote listen all key off that helper
- Edit Song / `_load_audio_path` often **replace** with a single `AudioTrack(id="main_audio", role="main")`

So: persistence can store multiple tracks; **behavior is replace-only single bed**.

### 2.3 What stays song-owned (variants must not steal)

- All **marks** and mark-lane configuration  
- Cue IDs / NOW / cue-list chrome  
- Setlist identity (`name`, `ma_export_name`, `setlist_number`, `note`, `row_color`, `category_id`)  
- Shared **video_clips** for MVP (VJ lane aligns to song timeline; switching audio variants should not orphan marks)  
- Project-level audio output / MA export settings  

---

## 3. Audit — persistence format

| Item | Today |
|------|-------|
| `SCHEMA_VERSION` | `1` (`domain.models`) |
| Song JSON | Includes full `audio_tracks[]` with path/role/flags/offset |
| Migration | `0 → 1` only (`migrate_project_dict`); no structural track migration |
| Bundle / Media layout | Walks **all** `song.audio_tracks` paths (already multi-path aware) |
| Relink | Scans track paths (and video); not variant-aware yet |

**Conclusion:** On-disk multi-track is partially ready; missing is an explicit **selected variant**, typed media bag for future kinds, and call-site discipline so loads never assume “the only” track is `tracks[0]` without selection semantics.

---

## 4. Assumptions that “a Song owns exactly one audio file”

These are the hotspots any implementation must retarget (audit counts from `src/cueplayer`):

| Assumption site | Pattern | Approx. |
|-----------------|---------|---------|
| `MainWindow._main_audio_path_for_song` | main-or-`[0]` | central |
| `MainWindow._load_audio_path` / activate | rebuilds single `main_audio` track | high |
| `ShowSessionService` activate | uses main track path for buffer load | medium |
| Timeline / remote / BPM / LTC detect | `_song_has_main_audio_file` / main path | medium |
| Edit Song dialog apply | `audio_tracks[0]` read/write | medium |
| Tests / fixtures | construct one `role="main"` track | many |

Engine itself holds **one** `AudioBuffer` and `set_song(Song)` — correct for “one selected variant at a time”; do not put multiple PCM beds on the clock.

---

## 5. Proposed domain model

### 5.1 Concepts

```text
Project
 └── Song                         # cue timeline + setlist identity
      ├── marks / mark_lanes      # NEVER per-variant
      ├── video_clips             # MVP: song-shared (future: optional variant video)
      ├── variants[]              # media packages
      ├── selected_variant_id     # which package feeds playback
      └── (legacy) audio_tracks   # transitional mirror — see §7
```

### 5.2 Implemented domain types (Task 2)

Flat MVP variant (Task 2) — simpler than the earlier media-bag sketch; still
extensible via ``kind`` + ``metadata``. Multi-item media bags can return later
without moving marks.

Module: ``cueplayer.domain.song_variant``

```text
VariantKind = "audio" | "video" | "ltc" | "click"

SongVariant
  id: str                 # required — selection / future persistence
  name: str               # required — operator label
  kind: VariantKind       # required (default audio) — future media kinds
  path: Path              # required — primary media file (may be missing on disk)
  anchor_offset: float    # optional (default 0) — Align Anchors later
  enabled: bool           # optional (default True) — soft-disable
  metadata: dict[str,str] # optional — extensible string bag
```

Song fields (in-memory; **not** persisted yet):

```text
Song.variants: list[SongVariant]
Song.selected_variant_id: str | None
```

Helpers: ``selected_variant()``, ``selected_audio_path()``, ``select_variant()``,
``ensure_variants_from_legacy_audio_tracks()``, ``duplicate()`` copies variants.

### 5.2b Earlier media-bag sketch (superseded for MVP)

```text
VariantMediaKind = "audio" | "video" | "ltc" | "click"   # extend later

SongVariantMedia
  id: str
  kind: VariantMediaKind
  path: Path
  # Future per-kind fields (channel map, gain, trim) — omit in MVP

SongVariant
  id: str
  name: str                      # display label ("Old mix", "v2")
  color: str                     # setlist/timeline chrome later
  media: list[SongVariantMedia]  # MVP: exactly one kind=="audio"
  offset_seconds: float = 0.0    # media shift vs song timeline (Align later)
  # Optional overrides (None = inherit song):
  file_ltc_side: FileLtcSide | None = None
  # Probed cache (optional; song.duration_seconds remains timeline authority):
  source_duration_seconds: float | None = None
```

**Task 2 chose the flat model** (`kind`+`path`+`anchor_offset`) for a smaller
domain surface. Persistence (Task 3) should serialize the flat fields.

### 5.3 Song additions (proposed)

```text
Song
  variants: list[SongVariant] = []
  selected_variant_id: str | None = None
  # Keep audio_tracks during transition (§7) OR derive via helper
```

### 5.4 Domain helpers (proposed API — not implemented yet)

| Helper | Behavior |
|--------|----------|
| `song.selected_variant()` | Resolve by id; else first variant; else `None` |
| `song.selected_audio_path()` | Path of selected variant’s primary `kind=="audio"` media |
| `song.select_variant(id)` | Set selection; validate id ∈ variants |
| `song.ensure_variant_from_legacy_tracks()` | Used by migration / load shim |

**Playback rule:** `AudioEngine` continues to load **one** buffer from `selected_audio_path()` (+ offset applied at load/seek policy in a later task). Marks always use song timeline seconds.

**Duration rule (MVP):** `Song.duration_seconds` remains the timeline length. When the selected variant’s audio is longer/shorter, follow existing “probe and extend/clamp” policy on the **song**, not a parallel per-variant timeline for cues.

---

## 6. Persistence schema (Task 3 — implemented)

### 6.1 Version

- `SCHEMA_VERSION = 2` (`domain.models`)

### 6.2 Song JSON fields (v2)

```json
{
  "variants": [
    {
      "id": "variant-main_audio",
      "name": "Main",
      "kind": "audio",
      "path": "Media/…/main.wav",
      "anchor_offset": 0.0,
      "enabled": true,
      "metadata": { "legacy_track_id": "main_audio", "legacy_role": "main" }
    }
  ],
  "selected_variant_id": "variant-main_audio",
  "audio_tracks": [ … ]
}
```

Paths use existing Unicode-safe relative/absolute helpers. ``metadata`` is a
string→string map only.

### 6.3 Component boundary

| Component | Role |
|-----------|------|
| ``ProjectRepository`` | `load` / `save` / `autosave` / `backup` / `exists` only |
| ``persistence.project_store`` | UTF-8 JSON encode/decode of domain objects |
| ``persistence.project_migrations`` | `migrate_project_dict` (0→1→2); **not** in Repository |

### 6.4 Backward compatibility

1. Load schema 0/1 → `migrate_project_dict` upgrades to 2.  
2. v1 songs without `variants` get variants synthesized from `audio_tracks` (main preferred for selection).  
3. Save always writes `schema_version: 2` plus `variants` / `selected_variant_id`.  
4. Phase A: continue writing legacy `audio_tracks` unchanged (call sites still use them).  
5. Downgrade not supported (`SchemaError` if file newer than supported).

### 6.5 Future schema evolution

- New fields: additive on variant dict with defaults in `_variant_from_dict`.  
- Breaking changes: bump `SCHEMA_VERSION`, add `if version == N:` step in `project_migrations.py` only.  
- Never put migration or auto-repair in `ProjectRepository`.

---

## 6b. Persistence schema proposal (Task 1 sketch — historical)

### 6.1 Bump (historical)

- `SCHEMA_VERSION = 2`

### 6.2 Song JSON (v2)

```json
{
  "id": "…",
  "name": "開場",
  "duration_seconds": 240.0,
  "selected_variant_id": "var_a",
  "variants": [
    {
      "id": "var_a",
      "name": "Main",
      "color": "#2BB673",
      "offset_seconds": 0.0,
      "file_ltc_side": null,
      "source_duration_seconds": 240.0,
      "media": [
        { "id": "m1", "kind": "audio", "path": "Media/…/main.wav" }
      ]
    },
    {
      "id": "var_b",
      "name": "Old mix",
      "color": "#5B8DEF",
      "offset_seconds": 0.12,
      "media": [
        { "id": "m2", "kind": "audio", "path": "Media/…/old.wav" }
      ]
    }
  ],
  "marks": [ … ],
  "video_clips": [ … ],
  "audio_tracks": [ … ]
}
```

### 6.3 Transitional `audio_tracks` on disk

**Phase A (recommended):** Continue writing a **derived** `audio_tracks` mirror for one schema generation:

- Selected variant → `role: "main"`
- Other variants with audio → `role: "reference"` (id/name/path/offset/color copied)

This keeps older tooling / mid-upgrade agents that still read `audio_tracks` from breaking, and matches bundle collectors that already iterate tracks.

**Phase B (later):** Stop requiring `audio_tracks` on load once all call sites use variants; still accept legacy-only files via migration.

---

## 7. Migration & backward compatibility

### 7.1 Load path (`schema_version` 1 → 2)

For each song in `migrate_project_dict` / `project_from_dict`:

1. If `variants` already present → keep; ensure `selected_variant_id` valid.  
2. Else build variants from `audio_tracks`:
   - Prefer track with `role == "main"` as selected; else `tracks[0]`.
   - Each track → one `SongVariant` with one `media` audio item; copy `name`, `color`, `offset_seconds`, path.
   - If **no** tracks → `variants = []`, `selected_variant_id = None` (video-only / empty song OK).
3. Set `selected_variant_id` to the main-derived variant id.  
4. Preserve marks/video/timebase unchanged.

### 7.2 Save path

- Always emit `schema_version: 2`, `variants`, `selected_variant_id`.  
- Phase A: also emit derived `audio_tracks` mirror.  
- Paths remain Unicode-safe relative/absolute via existing `_path_to_str` / `_str_to_path`.

### 7.3 Runtime compatibility shim (implementation task — not this doc’s code)

Until call sites are retargeted:

```text
selected_audio_path(song)  →  used by load / BPM / remote
legacy readers of audio_tracks[0]  →  update or route through helper
```

Prefer **one helper** in domain (or a tiny application façade) over scattering `variants[0]` guesses.

### 7.4 Downgrade

Not supported (same as today): newer schema_version refused with `SchemaError`.

---

## 8. Incremental implementation path

Aligns with roadmap Feature Sprint but **reframes** “Reference lanes” as **Variants (select one)** first — simultaneous compare/Align Anchors become a follow-on.

| Step | Work | Touches playback? | Touches UI? |
|------|------|-------------------|-------------|
| **T1** | This design (done) | No | No |
| **T2** | Domain types + helpers + unit tests | No | No |
| **T3** | Schema v2 migrate/load/save + golden fixtures | No* | No |
| **T4** | Retarget `_main_audio_path_for_song` / ShowSession / remote to `selected_audio_path` | Load path only (same one-buffer behavior) | No redesign |
| **T5** | Variant CRUD API (add/remove/select) without fancy chrome | Minimal | Minimal list/actions later |
| **T6** | UI variant picker / labels | No clock change | Yes (later task) |
| **T7** | Align Anchors / offset edit / optional compare hear | Careful | Yes |
| **T8** | Variant media kinds video/LTC/click | Optional | Later |

\*Persistence tests only; engine still one buffer.

**Relationship to earlier roadmap wording:**  
“Multi-audio Reference + Align Anchors MVP” becomes:

1. **Variants foundation** (select one for playback) — this design  
2. **Align / compare UX** — uses `offset_seconds` + optional non-selected variant audition, without attaching cues to a variant  

---

## 9. Risks

| Risk | Mitigation |
|------|------------|
| Dual model (`audio_tracks` + `variants`) drifts | Single write path: variants authoritative; tracks derived |
| Marks tied to wrong media after switch | Cues never store variant id; document that offsets must be applied carefully |
| Duration jumps on variant switch | Keep song.duration policy explicit; tests for shorter/longer beds |
| LTC side per file vs song | MVP inherit song `file_ltc_side`; optional per-variant override later |
| Bundle/relink miss new paths | Extend scanners to `variants[].media[].path` (tracks mirror helps Phase A) |
| Scope creep into simultaneous multi-hear | Gate behind T7; T2–T5 stay select-one |
| BPM stored on song but audio changes | Re-detect or clear `bpm_auto` on select (product decision in T5/T6) |

---

## 10. Estimated implementation tasks (post-design)

| ID | Task | Size |
|----|------|------|
| **I1** | Add `SongVariant` / `SongVariantMedia` + Song fields + helpers + tests | M |
| **I2** | `SCHEMA_VERSION=2` + migrate 1→2 + round-trip fixtures | M |
| **I3** | Compatibility: derive/sync `audio_tracks`; retarget main-path helpers | M |
| **I4** | Select-variant application API (no UI redesign) | S–M |
| **I5** | Minimal UI: choose variant / add audio as new variant | M |
| **I6** | Docs: PRODUCT_SPEC / AGENTS / roadmap checkoff | S |
| **I7** | (Future) Align Anchors + offset | M |
| **I8** | (Future) Extra media kinds on variant | M–L |

**Suggested next code task after this design:** **I1** (domain types + tests only) or **I1+I2** if a single PR is preferred — still **no UI redesign** and **no intentional playback behavior change** beyond reading the same file via the new accessor.

---

## 11. Design decisions log

| Decision | Choice | Why |
|----------|--------|-----|
| Variant vs simultaneous Reference-first | **Variants (select one)** first | Matches Task 1 goals; safer clock; marks stay song-global |
| Marks ownership | Song only | Cue accuracy across mix revisions |
| Video in MVP | Stay on Song | Avoid splitting VJ lane per mix until needed |
| Schema | v2 + migrate from `audio_tracks` | Backward compatible |
| Keep emitting `audio_tracks` | Phase A mirror | Soft landing for bundle/tests/call sites |
| Engine buffers | Still one | Sole sample clock |

---

## 12. Task 2 status — domain foundation (done)

| Deliverable | Status |
|-------------|--------|
| `domain/song_variant.py` | ✅ |
| `Song.variants` / `selected_variant_id` + helpers | ✅ |
| Unit tests `tests/domain/test_song_variant.py` | ✅ |

## 13. Task 3 status — persistence integration (done)

| Deliverable | Status |
|-------------|--------|
| `SCHEMA_VERSION = 2` | ✅ |
| Serialize/deserialize variants | ✅ |
| `persistence/project_migrations.py` (0→1→2) | ✅ |
| Repository stays load/save only | ✅ |
| Tests `tests/persistence/test_song_variants.py` | ✅ |
| UI / playback / timeline | ❌ unchanged |

### Remaining migration risks

- Dual write (`audio_tracks` + `variants`) can still drift if callers mutate tracks without `replace_main_audio`
- Legacy files with empty `audio_tracks` get empty variants (video-only OK)
- `metadata` values coerced to strings only

### Technical debt (after Task 3; see Task 4 for playback updates)

- Bundle/relink scanners not yet variant-path primary (tracks mirror helps)
- No derived tracks-from-variants on save (Phase A keeps caller-owned tracks)

---

## 14. Task 4 status — Playback Variant Support MVP (done)

| Deliverable | Status |
|-------------|--------|
| `Song.active_audio_path()` (variant → legacy tracks) | ✅ |
| `Song.replace_main_audio` / `clear_audio_media` dual-write helpers | ✅ |
| `PlaybackService.resolve_active_audio_path` / `active_variant` | ✅ |
| `ShowSessionService` arming uses PlaybackService resolve | ✅ |
| `MainWindow._main_audio_path_for_song` → PlaybackService | ✅ |
| Open Audio / Edit Song replace keep variants coherent | ✅ |
| Anchor offset applied at load | ❌ (Task 6) |
| UI variant picker / CRUD | ❌ (later) |
| Timeline / Waveform redesign | ❌ |

### 14.1 Active variant resolution flow

```text
ShowSessionService._prepare_waveform_and_audio
  └─ PlaybackService.resolve_active_audio_path(song)
       └─ Song.active_audio_path()
            1. selected_audio_path()  → enabled selected audio variant path
            2. else legacy main / audio_tracks[0]
  └─ host cache / _load_audio_path(path) → AudioEngine.set_buffer (one buffer)

MainWindow helpers (BPM / LTC / remote listen / “has audio”)
  └─ _main_audio_path_for_song → same resolve + is_file() gate
```

Rules:

- **Song** owns `selected_variant_id` and the variant list (exactly one active selection).
- **PlaybackService** resolves path only — no Align / offset / multi-buffer logic.
- **Timeline / marks** stay on Song; switching the bed does not move cues.
- **AudioEngine** still receives one media path / one PCM buffer (sole sample clock).

### 14.2 Playback flow before / after

| | Before | After (Task 4) |
|--|--------|----------------|
| Resolve | `audio_tracks` main / `[0]` in UI + ShowSession | `PlaybackService.resolve_active_audio_path` → `Song.active_audio_path` |
| Engine | `set_buffer` one bed | unchanged |
| Marks | Song-scoped | unchanged |
| No variants | tracks only | same fallback (identical runtime) |
| With variants | N/A (ignored) | selected enabled audio variant wins |

### 14.3 Backward compatibility

- Empty `variants` + populated `audio_tracks` → path from tracks (pre-variant / new Open Audio before dual-write creates variants).
- Schema v2 songs with one migrated variant → same file as former main track.
- Open Audio / Edit Song media replace: `replace_main_audio` updates tracks; if variants exist, collapses to one selected audio variant so resolve cannot stick on a stale path.
- Media clear: `clear_audio_media` clears tracks + variants + selection.

### 14.4 Remaining playback limitations

- No UI to select / add / remove variants (selection is domain/API only).
- `replace_main_audio` collapses multi-variant lists (replace-only habit) — CRUD must not rely on Open Audio for multi-mix.
- `anchor_offset` stored but **not** applied to load / playhead / waveform paint.
- Duration policy on shorter/longer beds unchanged (still overwrites `song.duration_seconds` from loaded buffer).
- Remote / bundle / relink still largely track-oriented (Phase A mirror).

### 14.5 Technical debt

- Dual model drift if any call site still assigns `audio_tracks = […]` without `replace_main_audio`.
- Waveform peaks keyed by file path only — no offset-aware cache key yet.
- BPM / file-LTC still song-level; switching beds does not auto re-detect.
- EventBus not used for “active variant changed”.

### 14.6 Risks

| Risk | Mitigation |
|------|------------|
| Stale variant after Open Audio | `replace_main_audio` syncs / collapses variants |
| Marks “wrong” vs new mix | Expected until Task 6 applies mapping; cues stay song-global |
| Accidental multi-variant wipe | Document; CRUD must use `select_variant`, not Open Audio |
| Clock / second buffer creep | Resolve returns one path only; engine unchanged |

### 14.7 Future extension points (Anchor Alignment)

| Extension | Where |
|-----------|--------|
| Apply `variant.anchor_offset` when mapping media time ↔ song timeline | Call `domain.anchor_mapping` from load/scrub/paint — not inside AudioEngine clock math |
| Align Anchors UI edits offset | Mutate `SongVariant.anchor_offset` on Song; keep marks fixed |
| Compare / audition non-selected | Optional second decode **outside** the sole clock (or muted offline) — never a second master clock |
| Offset-aware waveform | Paint transform using mapping; cache key includes offset |

---

## 15. Task 5 status — Anchor Mapping Foundation (done)

| Deliverable | Status |
|-------------|--------|
| `domain/anchor_mapping.py` | ✅ |
| `song_to_variant_time` / `variant_to_song_time` | ✅ |
| Unit tests `tests/domain/test_anchor_mapping.py` | ✅ |
| PlaybackService / Timeline / Waveform / UI | ❌ Task 5 unchanged (see Task 6) |
| Offset applied during playback | ✅ Task 6 (PlaybackService + playhead bridge) |

### 15.1 Mapping API

```text
domain.anchor_mapping
  coerce_anchor_offset(value) -> float
  resolve_anchor_offset(offset=None, *, variant=None) -> float
  song_to_variant_time(song_time, offset=None, *, variant=None) -> float
  variant_to_song_time(variant_time, offset=None, *, variant=None) -> float
  clamp_non_negative(time) -> float          # helper for later playback
  variant_time_in_media(t, *, media_duration) -> bool
```

### 15.2 Mapping formulas

Song Time is canonical. Variants never move cues.

```text
variant_time = song_time - anchor_offset
song_time    = variant_time + anchor_offset
```

Equivalent: media sample `0` aligns with song time `+anchor_offset`
(same spirit as legacy `AudioTrack.offset_seconds` → migrated `anchor_offset`).

### 15.3 Positive vs negative offsets

| Offset | Meaning | At song time 0 |
|--------|---------|----------------|
| `+0.5` | Media delayed on song timeline | Variant time `-0.5` (before file start) |
| `0` | Identity | Variant time `0` |
| `-0.25` | Media starts early vs song | Variant time `+0.25` (skip file head) |

Align Anchors UI (later) should edit `SongVariant.anchor_offset` only — never rewrite mark times.

### 15.4 Edge cases

| Case | Behavior |
|------|----------|
| `offset is None` / missing variant | Treat as `0.0` |
| Non-finite / unparsable offset | Coerce to `0.0` |
| Mapped time `< 0` or past media end | **Not clamped** by mapping API — raw float; Task 6 chooses silence / clamp / seek policy |
| Cues / Timeline / exporters | Always Song Time; ignore mapping unless explicitly converting for media I/O |
| Auto alignment (future) | Write a proposed `anchor_offset` via this API’s inverse; do not invent a second formula |

### 15.5 Future extension for automatic alignment

1. Detect shared anchors (manual marks or cross-correlation spike).  
2. Compute `anchor_offset = song_anchor_time - variant_anchor_time`.  
3. Store on `SongVariant.anchor_offset`.  
4. All consumers keep calling `song_to_variant_time` / `variant_to_song_time`.

No cross-correlation or multi-anchor conform in this task.

### 15.6 Test coverage

- Zero / positive / negative offsets  
- Round-trip both directions  
- Variant object vs explicit offset precedence  
- Coercion edge cases (None, NaN, Inf, bad strings)  
- No-clamp default + helper utilities  
- Module import isolation (no Qt / cueplayer runtime deps)

### 15.7 Remaining work after Task 5 (superseded by Task 6 for seek)

Task 6 wires seek / loop / playhead mapping. Still open after Task 6:

- Waveform paint offset transform + cache keys  
- Duration / end-of-media policy when offset pushes content  
- Remote bridge still seeks `engine` directly (Song Time)  
- Align Anchors UI  

### 15.8 Risks

| Risk | Mitigation |
|------|------------|
| Second ad-hoc `± offset` in UI/engine | Single module; PlaybackService imports `anchor_mapping` only |
| Clamp policy surprises | Engine still clamps Variant Time to `[0, duration]`; Song Time may map before 0 |
| Remote bypass | Documented for Task 7+ |

---

## 16. Task 6 status — Anchor Playback Integration (done)

| Deliverable | Status |
|-------------|--------|
| PlaybackService uses `anchor_mapping` for seek / loops / position | ✅ |
| AudioEngine receives Variant Time on seek / loop points | ✅ |
| Song Time for Timeline playhead / session / mark-at-playhead | ✅ |
| Timeline / Waveform redesign | ❌ |
| Align Anchors UI / auto-align | ❌ |
| Cue time fields mutated | ❌ |

### 16.1 Playback mapping flow

```text
Before (offset ignored):
  UI Song Time ──seek──► AudioEngine (treated as media time)
  AudioEngine.position ──► Timeline playhead (same number)

After (Task 6):
  UI Song Time
    └─ PlaybackService.seek
         └─ song_to_variant_time (anchor_mapping only)
              └─ AudioEngine.seek(Variant Time)

  AudioEngine.position (Variant Time)
    └─ PlaybackService.engine_to_song_time / position
         └─ Timeline / monitor / session (Song Time)

  A–B loop: Song Time at façade ↔ Variant Time stored on engine
```

Zero / missing offset ⇒ identity (legacy behavior unchanged).

### 16.2 How anchor offsets are applied

- Only through `domain.anchor_mapping` (`song_to_variant_time` / `variant_to_song_time`).
- PlaybackService helpers: `song_to_engine_time` / `engine_to_song_time` / `active_anchor_offset`.
- No duplicated `± offset` arithmetic in UI or engine.
- Cues keep stored Song Time; export / NOW / cue list unchanged.

### 16.3 Why Timeline still uses Song Time

Marks, video clips, executors, and MA export are authored on the Song timeline.
Switching variants or editing `anchor_offset` must not rewrite those coordinates.
Timeline paints Song Time; mapping only translates the media bed under the playhead.

### 16.4 Remaining work for Align Anchors UI (Task 7+)

- Design: pick song anchor + variant anchor → set `SongVariant.anchor_offset`
- No auto cross-correlation yet (manual first)
- Optional compare hear without second master clock
- Waveform overlay / offset-aware paint (optional follow-on)
- Route Remote seek through PlaybackService

### 16.5 Test coverage

- Seek identity at offset 0 / legacy tracks  
- Seek Song→Variant with positive offset; session/position read back Song Time  
- Loop region Song↔Variant round-trip on façade  
- Domain `test_anchor_mapping` still green  

### 16.6 Remaining integration work

- Waveform peaks paint not offset-shifted  
- Some MainWindow helpers still read `engine.position` for drop/paste UX  
- Web remote `engine.seek` bypass  
- Song duration vs media duration when offset ≠ 0  

### 16.7 Risks

| Risk | Mitigation |
|------|------------|
| Engine clamp at 0 hides pre-roll Song Time | Document; Align UI can warn |
| Direct `engine.seek` callers | Prefer PlaybackService; fix Remote later |
| Waveform vs audio skew with offset | Task 7+ paint transform |

### Recommended Feature Task 7

**Align Anchors UI Design** — product/UX design for editing `anchor_offset` (manual anchor pair) without redesigning Timeline coordinates or moving cues. Implementation of chrome can follow the design doc.

---

## 17. Sprint 4.5 — Production Validation (done, docs only)

**Scope tip:** `cursor/sprint45-variant-validation-028d`  
**Code changes:** none.

Song Variant MVP stack (Tasks 1–6) was reviewed against real show-prep workflows.
This section is the audit record + operator checklist.

### 17.1 Architecture verification (code review)

| Claim | Verdict | Evidence |
|-------|---------|----------|
| Song Time is canonical | ✅ Hold | Marks / video clips / MA plan use `Mark.time_seconds` / song timeline; no variant id on cues |
| Cue timing never depends on Variant | ✅ Hold | `Song.add_mark` / exporters ignore variants; Task 6 mark-at-playhead uses `playback.position` (Song Time) |
| Anchor mapping is the only Song↔Variant conversion | ✅ Hold (desktop playback) | Only `domain/anchor_mapping.py` defines `± offset`; PlaybackService wraps it — no duplicated formula in UI/engine |
| Playback works for legacy (no / empty variants) | ✅ Hold by design | `active_audio_path` falls back to `audio_tracks`; offset coerce → `0.0` (identity) |
| Playback works for multi-variant (selected one) | ✅ Hold by design | `selected_variant` + path resolve + mapping on seek/loops |
| No duplicate mapping logic | ✅ Hold | Grep: conversion arithmetic only in `anchor_mapping`; PlaybackService delegates |

**Known bypasses (not duplicate formulas, but incomplete Song-Time façade):**

| Site | Issue | Severity |
|------|-------|----------|
| `web_remote/bridge.py` `engine.seek(...)` | Passes Song Time / mark times straight into engine (Variant Time expected when offset ≠ 0) | High when offset ≠ 0; OK at offset 0 |
| `MainWindow` drop/paste/add-video using `engine.position` | Places content at Variant Time if offset ≠ 0 | Medium when offset ≠ 0 |
| Waveform paint | Peaks keyed/drawn in file time; not offset-shifted | Medium visual skew when offset ≠ 0 |
| `AudioEngine.sync_offset_seconds` | Separate monitoring-latency calibration — **not** variant anchor; do not conflate | Document only |

### 17.2 Production validation checklist

Use on a Windows show machine with real media. Checkboxes are for operators / QA — not automated in this sprint.

#### A. Playback

- [ ] Legacy project (schema v1 / empty `variants`): Open → activate song → Play/Pause/Stop audible, no crash
- [ ] Migrated / v2 single-variant song: same bed as former main track
- [ ] Multi-variant song with `selected_variant_id` set: correct file loads (one buffer)
- [ ] Unicode / Chinese path still plays
- [ ] Offset `0.0`: playhead, music, and marks feel identical to pre-MVP

#### B. Seek

- [ ] Timeline click-seek lands playhead on Song Time (transport / NOW agree)
- [ ] Transport scrub / seek agrees with Timeline
- [ ] With `anchor_offset = +0.5`: seeking to song `10.0` auditions media near `9.5` (silence/clamp near song `0` if mapped variant time `< 0`)
- [ ] With `anchor_offset = 0`: seek numbers match media 1:1

#### C. Loop

- [ ] Set A/B on Timeline (Song Time); loop engages
- [ ] Loop region audible matches Song Time handles at offset `0`
- [ ] With non-zero offset: loop still frames the intended song region (engine stores Variant Time via PlaybackService)
- [ ] Clear loop / disable still works

#### D. Mark at playhead

- [ ] While stopped/scrubbing: mark uses Timeline playhead (Song Time)
- [ ] While playing: mark uses `playback.position` (Song Time), not raw engine media time
- [ ] Cue list / NOW / export still show same `time_seconds` after variant path changes (offset 0)
- [ ] Changing selection / offset later must **not** rewrite existing mark times

#### E. Song switching

- [ ] Setlist next/prev activates new song; waveform/PCM arm from `resolve_active_audio_path`
- [ ] Switching away mid-play quiesces cleanly; no second clock
- [ ] Song B with different selected variant loads that path only
- [ ] Zoom/view keep policy unchanged for `replace_track=False` activate

#### F. Legacy projects

- [ ] Open pre-variant `.cueplayer` / bundle: migrates to schema v2; marks intact
- [ ] Empty `audio_tracks` + video-only song still opens
- [ ] Phase A still writes `audio_tracks` mirror on save
- [ ] Relink / missing-file UX still surfaces for track paths (variant-primary scanners deferred)

#### G. Multi-variant projects

- [ ] Two+ variants on disk JSON; only selected/enabled audio path arms engine
- [ ] Disabled selected variant falls back to first enabled (`selected_variant` rules)
- [ ] Non-audio selected kind does not supply `selected_audio_path` (falls back / empty)
- [ ] `replace_main_audio` / Open Audio collapses variants (document operator surprise until CRUD UI)

#### H. Error cases

- [ ] Missing media file: no crash; loading/status path; engine buffer cleared or prior behavior preserved
- [ ] All variants disabled / no resolvable audio: activate does not throw; timeline placeholder OK
- [ ] Corrupt / unreadable audio: existing warning dialog path
- [ ] Remote seek with non-zero offset: **expect skew until Remote uses PlaybackService** (known gap)

### 17.3 Remaining technical debt

| Item | Notes |
|------|-------|
| Dual write `audio_tracks` + `variants` | Drift if callers assign tracks without `replace_main_audio` |
| Remote transport bypasses PlaybackService | Seek/mark seek ignore mapping |
| Scattered `engine.position` in MainWindow | Drop/paste/video-add/timecode refresh |
| Waveform not offset-aware | Paint/cache ignore `anchor_offset` |
| `replace_main_audio` collapses multi-variant | Blocks safe Open Audio while keeping alternate mixes |
| No variant CRUD / picker UI | Selection is API/persistence only |
| Bundle/relink still track-primary | Phase A mirror helps; scanners not variant-first |
| Stale comment on `active_audio_path` (“playback integration later”) | Docs/code comment drift only |

### 17.4 Remaining architectural risks

| Risk | Why it matters | Mitigation direction |
|------|----------------|----------------------|
| Second timebase confusion | Operators think engine position == Song Time | Finish Song-Time façade; Remote through PlaybackService |
| Silent offset skew on Remote / paste | Show-day wrong cue placement | Block Align UI ship until Remote + paste paths mapped |
| Dual model drift | Wrong bed after Edit Song / Open Audio | Single write helpers; later derive tracks from variants |
| Duration vs media length with offset | Song end ≠ file end | Explicit duration policy in Align / playback polish |
| Conflating `sync_offset_seconds` with `anchor_offset` | Calibration vs mix align | Keep separate; never reuse engine sync for variants |

### 17.5 Remaining UX gaps

| Gap | Operator impact |
|-----|-----------------|
| No variant list / select / add / rename | Cannot manage mixes without hand-editing JSON |
| No Align Anchors chrome | Cannot set `anchor_offset` in-app |
| No waveform overlay / offset preview | Hard to trust align by ear alone |
| Open Audio wipes extra variants | Easy to destroy alternate mixes |
| No badge for “non-zero offset active” | Easy to miss why seek “sounds early/late” |
| Remote not offset-safe | Tablet control wrong with aligned mixes |

### 17.6 Recommended priority for future implementation

1. **P0 — Align Anchors UX** (next): manual anchor pair → `anchor_offset`; no cue moves; no Timeline redesign.  
2. ~~**P0 — Close Song-Time façade holes**~~ → **Done in Sprint 5 Task 1** (Remote + MainWindow paste/drop).  
3. **P1 — Variant picker / CRUD (minimal)**: select + add audio as variant without collapsing on Open Audio.  
4. **P1 — Offset-aware waveform paint** (or clear “media vs song” indicator).  
5. **P2 — Auto / cross-correlation align**; compare-hear without second master clock.  
6. **P2 — Bundle/relink variant-primary**; Phase B drop `audio_tracks` requirement.

### 17.7 MVP readiness verdict

| Area | Ready for production rehearsal? |
|------|----------------------------------|
| Legacy projects, offset 0, single bed | **Yes** — treat as validated by design + unit coverage; run checklist A/B/D/E/F on site |
| Multi-variant select-one, offset 0 | **Yes** if variants authored in JSON / tests; **no in-app CRUD** |
| Non-zero `anchor_offset` on desktop seek/loop/playhead | **Conditionally yes** for lab; Remote + some paste paths **not** safe (closed in Sprint 5 Task 1) |
| Align / compare UX | **No** — design next |

---

## 18. Sprint 5 Task 1 — Song-Time Façade Completion (done)

**Scope tip:** `cursor/sprint5-song-time-facade-028d`

### 18.1 Remaining Song-Time bypasses — before / after

| Entry point | Before | After |
|-------------|--------|-------|
| Web Remote `seek` / `seek_mark` / `stop` | `host.engine.seek(Song Time)` | `host.seek_song_time` → PlaybackService → AnchorMapping → engine |
| Web Remote clock / state `position` | `engine.position` (Variant) | `host.song_position()` (Song Time) |
| Web Remote loop payload | raw `engine.loop_a/b` (Variant) | `host.song_loop_a/b` (Song Time) |
| Web Remote monitor meta `position` | engine Variant Time | Song Time; buffer slice still Variant Time |
| Web Remote video listen start | engine position | Song Time into mixer |
| MainWindow paste / drop / add-video / cue-list refresh / transport after load | `engine.position` | `playback.position` |
| Live WebRTC PCM cursor | `engine.position` | **Unchanged** (media / Variant Time — correct) |
| `AudioEngine` internal loop/end seeks | engine self | **Unchanged** (Variant Time internals) |
| Sync calibration dialog `engine.seek(0)` | media start for latency cal | **Unchanged** (intentional Variant Time) |

### 18.2 Updated dependency graph

```text
External transport / cues / paste / remote UI (Song Time)
        │
        ▼
PlaybackService  ──song_to_variant_time / variant_to_song_time──►  domain.anchor_mapping
        │
        ▼
AudioEngine (Variant / media Time only on seek & loop points)
        │
        ├── position_changed ─► MainWindow bridge ─► Timeline (Song Time)
        └── raw position ─► WebRTC listen cursor / engine internals (Variant Time)

RemoteHost
  seek_song_time / song_position / song_loop_*  →  PlaybackService
  engine.position / engine.seek                 →  Variant Time only (not for transport)
```

### 18.3 Risks

| Risk | Notes |
|------|-------|
| Future `engine.seek` from new code | Boundary tests assert bridge has no `engine.seek(` |
| Waveform still file-time | Visual skew with non-zero offset until Align UX / paint work |
| Duration still media length | Song end vs file end with offset still policy-open |
| Sync calib vs anchor | Keep `sync_offset_seconds` separate from `anchor_offset` |

### 18.4 Recommendation for Sprint 5 Task 2

**Align Anchors UX** — design + minimal chrome to edit `SongVariant.anchor_offset` (manual song/variant anchor pair) without moving cues or redesigning Timeline/Waveform. Façade is now safe enough for non-zero offset on desktop + remote transport.

---

## 19. Sprint 5 Task 2 — Align Anchors UX Design (done, docs only)

**Scope tip:** `cursor/sprint5-align-anchors-ux-028d`  
**Code changes:** none.

### 19.1 Design goals & non-goals

| Goal | Rule |
|------|------|
| Operator sets `SongVariant.anchor_offset` by ear/eye | Manual only |
| Cues / Timeline stay on Song Time | Never rewrite `Mark.time_seconds` |
| One selected variant at a time | Align edits the **active** (or dialog-selected) variant |
| Preview before commit | Draft offset ≠ persisted until Apply |
| Existing mapping math | `anchor_offset = song_anchor − variant_anchor` (see §15 / `anchor_mapping`) |

| Non-goal (this design) | Deferred |
|------------------------|----------|
| Timeline chrome redesign | Keep Song Time coordinates |
| Waveform paint redesign | Optional “draft offset” readout only |
| Auto cross-correlation | §19.8 |
| Full variant CRUD | Minimal select list inside Align panel is enough for Align v1 |
| Second playback clock / A–B compare hear | Later; sole clock remains AudioEngine |

### 19.2 UX flow (operator story)

```text
1. Select Variant     → choose which mix to align (must be audio + enabled + path OK)
2. Choose Anchor      → set Song Anchor (Song Time) + Variant Anchor (media time)
3. Preview Offset     → system computes draft_offset; playhead seeks via PlaybackService
4. Adjust Offset      → nudge draft (±frame / typed seconds) and re-preview
5. Apply              → write draft → SongVariant.anchor_offset; mark project dirty
6. Cancel             → discard draft; restore last applied offset for playback
7. Reset              → draft = 0.0 (identity); Apply still required to persist
```

**Invariant:** Timeline marks never move. Only the media bed under Song Time shifts.

### 19.3 Screen flow

Prefer a **modal dialog** (or tool-window) named **Align Anchors** — not a Timeline redesign.

```text
┌─ Align Anchors ──────────────────────────────────────────────┐
│ Variant: [ Main ▾ ]     path: …/床.wav     status: Ready     │
│                                                              │
│ Song Anchor (Song Time)     Variant Anchor (media)           │
│ [ Use playhead ] [ Use mark ▾ ]   [ Use media playhead ]     │
│  00:12.340                      00:11.840                    │
│                                                              │
│ Draft offset:  +0.500 s     Applied:  +0.000 s               │
│ [ −1f ] [ −10 ms ]  [ offset field ]  [ +10 ms ] [ +1f ]    │
│                                                              │
│ Duration (song / media / audible span) — see §19.6           │
│                                                              │
│ [ Preview ]  [ Reset ]              [ Cancel ]  [ Apply ]    │
└──────────────────────────────────────────────────────────────┘
```

Entry points (implementation later):

- Tools → **Align Anchors…**
- Optional: context on Music lane / variant badge (when picker exists)

While dialog is open:

- Timeline remains Song Time (unchanged paint model).
- Transport Play/Pause/Seek still go through PlaybackService (Song Time).
- **Preview** temporarily drives playback with `draft_offset` (session-local); **Cancel** restores applied offset.

### 19.4 Interaction model

| Step | Operator action | System behavior |
|------|-----------------|-----------------|
| Select Variant | Dropdown of song variants (audio, enabled preferred) | Selecting another variant reloads draft from that variant’s applied offset; warns if draft dirty |
| Choose Song Anchor | **Use playhead** or pick an existing mark | Stores `song_anchor` in Song Time; does not create a mark unless operator later chooses |
| Choose Variant Anchor | Scrub/seek then **Use media playhead** | Media playhead = current engine Variant Time (`playback` inverse); stores `variant_anchor` |
| Preview Offset | Click **Preview** (or auto after both anchors set) | `draft = song_anchor − variant_anchor`; seek to Song Anchor via PlaybackService using draft; brief status “Previewing draft offset” |
| Adjust Offset | Nudge buttons / typed field / mouse wheel on field | Updates draft; optional live re-preview if “Live preview” checked (default off to avoid scrub thrash) |
| Apply | Click **Apply** | Persist `variant.anchor_offset = draft`; dirty project; close or stay open (preference: stay open with toast) |
| Cancel | Click **Cancel** / Esc | Drop draft; re-apply last persisted offset to playback session; close |
| Reset | Click **Reset** | Set draft to `0.0`; does **not** persist until Apply |

**Anchor pair formula (must match domain):**

```text
draft_offset = song_anchor − variant_anchor
# same as: media sample 0 aligns with song time +offset
# song_to_variant_time(s) = s − offset
```

If only one anchor is set, Preview is disabled with hint “Set both anchors”.

### 19.5 Keyboard shortcuts (proposed)

| Shortcut | Context | Action |
|----------|---------|--------|
| `Esc` | Dialog focused | Cancel (confirm if draft dirty) |
| `Enter` | Dialog focused, Preview enabled | Preview |
| `Ctrl+Enter` | Dialog focused, Apply enabled | Apply |
| `[` / `]` | Dialog focused | Nudge draft −/+ 1 frame (song fps) |
| `Shift+[` / `]` | Dialog focused | Nudge −/+ 10 frames |
| `A` | Dialog focused | Capture Song Anchor from Timeline playhead |
| `Shift+A` | Dialog focused | Capture Variant Anchor from media playhead |

Do **not** steal global mark-digit shortcuts while dialog is open (modal).

### 19.6 Policies

#### Duration display

| Label | Meaning |
|-------|---------|
| **Song duration** | `song.duration_seconds` (canonical Timeline length; cues live here) |
| **Media duration** | Loaded buffer / file length (Variant Time span) |
| **Audible span (draft)** | Informational only: Song Times where mapped variant time ∈ `[0, media_duration)` |

Policy for Align v1:

- Timeline / transport duration **stay Song duration** (no silent rewrite on Apply).
- If media is shorter/longer than song after offset, show warning chip: “Media ends at song T=…” / “Silence before media starts”.
- Do **not** auto-shrink/grow `song.duration_seconds` on Apply (avoids moving relative cue layout unexpectedly). Optional later: “Fit song duration to media” checkbox (off by default).

#### Negative offset handling

- Allowed. Means media starts **before** song 0 (skip into file at song time 0).
- Preview at song 0 should audition `variant_time = −offset` (positive into file).
- Show draft with explicit sign (`+` / `−`) and a one-line gloss: “Negative: media leads the song timeline”.
- Engine clamp at media 0 still applies when seeking to Song Times that map before file start — status: “Before media start (silence)”.

#### Missing / disabled media

| Case | UI |
|------|-----|
| Variant path missing | Status **Missing file**; Preview/Apply disabled; offer Relink (existing project relink) |
| Variant disabled | Status **Disabled**; cannot Align until enabled (or enable toggle in dialog) |
| Non-audio kind | Hidden from Align dropdown (v1 audio-only) |
| No variants / legacy tracks only | Dialog offers “Use main bed” shim: treat active path as ephemeral Main; Apply writes offset onto selected/created main variant via existing domain helpers |
| Decode failure | Preview disabled; show loader error text |

### 19.7 Validation rules

| Rule | Enforce |
|------|---------|
| Finite offset | Reject NaN/Inf; coerce like `coerce_anchor_offset` |
| Both anchors for auto-compute | Preview from anchors requires both set |
| Typed offset always allowed | Can Apply typed draft without anchors (power user) |
| Confirm on Cancel if dirty | Draft ≠ applied |
| Confirm on variant switch if dirty | Don’t lose draft silently |
| Apply does not move marks | Hard invariant + test in implementation task |
| Offset range soft warn | Warn if `|offset| > media_duration` or `> song.duration` (still Allow) |

### 19.8 Error handling

| Error | Operator message | Recovery |
|-------|------------------|----------|
| Missing media | “Media file not found for this variant.” | Relink / pick another variant |
| Preview seek failed | “Could not preview offset.” | Check device / reload song |
| Apply while no selection | “Select a variant first.” | Select |
| Dirty Cancel | “Discard draft offset?” | Discard / Keep editing |
| Live preview stutter | Auto-disable live preview after N seeks/sec | Manual Preview button |

### 19.9 Mock interaction sequence

```text
GIVEN song「開場」with marks on Song Time; variant「Old mix」path OK; offset 0
WHEN  operator opens Align Anchors → selects「Old mix」
AND   seeks Timeline to kick (12.340 s) → Song Anchor = Use playhead
AND   scrubs until Old mix kick aligns by ear → Variant Anchor = Use media playhead (11.840)
AND   Preview → draft = +0.500 s; playhead at 12.340 sounds correct on Old mix
AND   Adjust +10 ms → draft = +0.510 s → Preview
AND   Apply
THEN  SongVariant.anchor_offset == 0.510
AND   all marks still at original Song Times
AND   desktop + remote seek to a mark still lands the kick under that mark
WHEN  Cancel after changing draft without Apply
THEN  playback returns to last applied offset; marks unchanged
WHEN  Reset → Apply
THEN  offset == 0.0 (identity)
```

### 19.10 Risks

| Risk | Mitigation |
|------|------------|
| Operators think Align moves cues | Copy in dialog: “Cues stay fixed — only the mix shifts” |
| Draft vs applied confusion | Always show both numbers; Preview badge |
| Waveform still unshifted | Status: “Waveform shows file time; trust playhead + ear in v1” |
| Open Audio collapsing variants | Align dropdown must not call `replace_main_audio` |
| Conflating sync calib offset | Separate menu; never write `engine.sync_offset_seconds` from Align |
| Modal blocks show | Allow non-modal tool window in implementation if operators need Timeline marks visible |

### 19.11 Future extension — automatic alignment

1. Operator marks Song Anchor (or uses selected mark).  
2. System searches a window of the selected variant for best correlation peak → proposes `variant_anchor`.  
3. Same Preview / Adjust / Apply path; never auto-Apply.  
4. Still one clock; offline analysis buffer OK; no second master clock.  
5. Multi-anchor conform / warp = out of scope until single-offset trusted.

### 19.12 Recommendation for implementation tasks

| ID | Task | Notes |
|----|------|-------|
| **I1** | Align Anchors dialog shell + variant dropdown | No Timeline redesign |
| **I2** | Capture Song/Variant anchors + draft offset compute | Use `anchor_mapping` only |
| **I3** | Preview/Cancel session: temporary draft offset for PlaybackService | Must not persist until Apply; Cancel restores |
| **I4** | Apply / Reset / dirty / undo | Persist `SongVariant.anchor_offset`; undoable |
| **I5** | Duration chips + missing-media / negative-offset copy | Policies §19.6 |
| **I6** | Tests: marks unchanged; seek maps with draft/applied; Cancel restores | |
| **I7** | (Later) Non-modal + optional waveform draft indicator | |
| **I8** | (Later) Auto-correlate propose | §19.11 |

**Suggested first implementation PR:** **I1–I4** (dialog + preview session + Apply), then **I5–I6**.

---

## 20. Sprint 5 Task 3 — Align Anchors Dialog Shell (done)

**Scope tip:** `cursor/sprint5-align-anchors-shell-028d`

### 20.1 Dialog structure

| Widget | Role |
|--------|------|
| `AlignAnchorsDialog` | Modal QDialog; no Timeline/playback mutation |
| `variant_combo` | Lists audio variants; shows path/status |
| Song / Variant anchor groups | Labels + capture buttons (stubs) |
| Draft / Applied offset row | Display + disabled draft spin; nudge stubs disabled |
| `preview_area` | Placeholder for duration chips |
| Preview / Reset / Apply / Cancel | Preview/Reset/Apply → status stub; Cancel → `reject()` |

### 20.2 Dialog architecture

```text
MainWindow Tools → Align Anchors…
        └─ AlignAnchorsDialog(song)
             ├─ reads Song.variants (display only)
             └─ stubs for capture / preview / apply / reset
                  (Task 4: Anchor Computation + preview session)
```

### 20.3 Planned integration points (Task 4)

- Capture playheads via PlaybackService (`song_position` / engine Variant Time)
- Compute `draft = song_anchor − variant_anchor` through `anchor_mapping` only
- Enable draft spin + nudges; Preview session without persisting
- Apply writes `SongVariant.anchor_offset` (marks unchanged)

### 20.4 Remaining implementation work

- Anchor computation + draft/applied model (Task 4)
- Preview session / Cancel restore playback mapping
- Apply + undo + dirty
- Duration chips / missing-media enablement rules
- Enable nudge controls

### 20.5 Risks

| Risk | Mitigation |
|------|------------|
| Operators think Apply works | Intro + status: “Shell only” |
| Shortcut clash with Timeline | Modal dialog; Esc closes |
| Premature offset writes | Apply stub does not mutate |

### 20.6 Recommendation for Task 4

**Anchor Computation** — wire capture + `draft_offset = song_anchor − variant_anchor` (via `anchor_mapping`), update draft display/nudges; still no Apply persistence (or Apply in Task 5 if preferred). Prefer: compute + display in Task 4; Preview/Apply session next.

---

## 21. Sprint 5 Task 4 — Anchor Computation (draft only, done)

**Scope tip:** `cursor/sprint5-anchor-computation-028d`

### 21.1 Draft computation flow

```text
Capture Song Anchor (playhead / mark)     → temporary _song_anchor
Capture Variant Anchor (media playhead) → temporary _variant_anchor
        │
        ▼
domain.anchor_mapping.offset_from_anchors(song, variant)
        = song_anchor − variant_anchor
        │
        ▼
Dialog draft_offset (spin + preview panel)
        │
        ├── Nudge / type → update draft only
        ├── Reset → draft = 0.0
        └── Apply → still non-destructive (Task 5)
```

MainWindow supplies read-only playhead callbacks (`playback.position`, `engine.position`); dialog never seeks.

### 21.2 Temporary state model

| Field | Lifetime | Persisted? |
|-------|----------|------------|
| `_song_anchor` | Dialog session | No |
| `_variant_anchor` | Dialog session | No |
| `_draft_offset` | Dialog session | No |
| `SongVariant.anchor_offset` | Project | Unchanged this task |

### 21.3 Validation rules (draft)

- Finite offsets via `coerce_anchor_offset`
- Both anchors required to recompute from pair; typed/nudged draft always allowed
- Missing playhead source → status message, no crash
- Apply never mutates project

### 21.4 Remaining Apply workflow (Task 5)

- Persist `draft_offset` → selected `SongVariant.anchor_offset`
- Dirty + undo
- Optional Preview session that temporarily drives PlaybackService mapping
- Cancel restore if preview session was active
- Confirm on dirty Cancel / variant switch

### 21.5 Test coverage

- `offset_from_anchors` round-trip with mapping
- Capture both anchors → draft; variant unchanged
- Nudge / Reset draft-only
- Apply stub non-mutating
- Use mark capture

### 21.6 Risks

| Risk | Mitigation |
|------|------------|
| Operators expect Apply to stick | Status: “Apply deferred” |
| Media vs Song playhead confusion | Labels + callbacks documented |
| Draft lost on close | Expected until Apply |

### 21.7 Recommendation for Task 5

**Anchor Apply / Commit** — write draft to `SongVariant.anchor_offset` with dirty/undo; keep marks fixed; optional playback preview session using existing Song-Time façade.

---

## READY FOR ANCHOR APPLY
