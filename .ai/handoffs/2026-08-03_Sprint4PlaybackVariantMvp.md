# Handoff — Sprint 4 Feature Task 4: Playback Variant Support MVP

**Date:** 2026-08-03  
**Branch:** `cursor/sprint4-playback-variant-mvp-028d`  
**Base:** `cursor/sprint4-song-variant-persistence-028d`

## Summary

Playback load now resolves the Song’s active variant (or legacy main track) via
`PlaybackService` → `Song.active_audio_path()`. AudioEngine still gets one buffer.
No UI / timeline redesign / anchor apply.

## Key files

- `domain/models.py` — `active_audio_path`, `replace_main_audio`, `clear_audio_media`
- `application/playback_service.py` — `resolve_active_audio_path`, `active_variant`
- `application/show_session_service.py` — uses resolve for waveform/PCM arm
- `ui/main_window.py` — `_main_audio_path_for_song`, replace/clear dual-write
- `docs/song_variant_design.md` — §14 flow / compat / limitations / Task 5

## Next

**READY FOR ANCHOR OFFSET FOUNDATION**
