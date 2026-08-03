# Next task

**Status:** Queued — awaiting human start  
**Type:** Feature — Playback variant support  
**Updated:** 2026-08-03  
**Workflow:** `READ → PLAN → IMPLEMENT → REPORT + HANDOFF → STOP`

**Previous:** Sprint 4 Feature Task 3 — Song Variant persistence  
See `.ai/REPORT.md` and `.ai/handoffs/2026-08-03_Sprint4SongVariantPersistence.md`  
Baseline: `docs/song_variant_design.md` (ends READY FOR PLAYBACK VARIANT SUPPORT)

---

## Current task

### Sprint 4 Feature Task 4: Playback variant support

**Do not auto-start until the user explicitly continues.**

### Goal

Retarget audio load paths to `song.selected_audio_path()` while keeping a single
AudioEngine buffer. No UI redesign; no timeline redesign.

### Read first

1. `docs/song_variant_design.md`
2. `MainWindow._main_audio_path_for_song` / ShowSession activate
3. `Song.selected_audio_path`

### Done when

- Selected variant feeds playback load; tests green; REPORT + handoff; STOP
