# Song Variants — Domain & Persistence Design

**Status:** Sprint 4 Feature Task 2 complete (Song Variant **domain foundation**)  
**Updated:** 2026-08-03  
**Scope tip:** `cursor/sprint4-song-variant-domain-028d`  
**Related:** [`roadmap.md`](roadmap.md) · [`PRODUCT_SPEC.md`](PRODUCT_SPEC.md) · [`architecture_overview.md`](architecture_overview.md)

**Task 2 constraint:** Domain model + unit tests only. No UI, no playback behavior change, no schema migration / ProjectService / Timeline changes.

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

## 6. Persistence schema proposal

### 6.1 Bump

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
| Persistence / schema migration | ❌ next task |
| Playback / UI | ❌ unchanged |

### Open design questions (before persistence)

1. Serialize `metadata` as opaque string map only, or allow nested JSON?
2. On migrate from `audio_tracks`, should hidden tracks become `enabled=False`? (domain helper currently does)
3. Keep emitting `audio_tracks` mirror forever in Phase A, or one schema generation only?

### Risks before persistence integration

- In-memory variants lost on save until schema v2  
- Call sites still use `_main_audio_path_for_song` / `audio_tracks`  
- Dual model drift if UI writes tracks but not variants  

### Recommended Feature Task 3

**Persistence integration:** schema v2, migrate 1→2, round-trip fixtures, optional derived `audio_tracks` mirror — still no UI redesign and no intentional playback behavior change beyond load accessors in a later slice.

---

## READY FOR PERSISTENCE INTEGRATION
