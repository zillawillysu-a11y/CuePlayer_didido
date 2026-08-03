# Song Variants — Domain & Persistence Design

**Status:** Sprint 4 Feature Task 6 complete (Anchor Playback Integration)  
**Updated:** 2026-08-03  
**Scope tip:** `cursor/sprint4-anchor-playback-028d`  
**Related:** [`roadmap.md`](roadmap.md) · [`PRODUCT_SPEC.md`](PRODUCT_SPEC.md) · [`architecture_overview.md`](architecture_overview.md)

**Task 6 constraint:** Playback wiring only. No Timeline/Waveform redesign,
Align Anchors UI, or automatic alignment. Cue times unchanged.

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

## READY FOR ALIGN ANCHORS UI DESIGN
