# Latest AI task report

**Date:** 2026-08-03  
**Branch:** `cursor/sprint2-playback-boundary-028d`  
**Audience:** ChatGPT / future Cursor review

---

## Task objective

Sprint 2 · Task 6 — **Playback Boundary Completion**: move remaining
playback-related MainWindow interactions (volume, loop, scrub, nudge) into
`PlaybackService` without redesigning AudioEngine or changing UI behavior.

## What was implemented

- Extended `application/playback_service.py` with volume/mute/gain, A–B loop
  (including fresh-pair A/B rules), scrub begin/end, nudge.
- MainWindow wires those paths through `playback.*` only.
- `_activate_song` left in MainWindow.
- Playback rate: documented as engine-internal device sample-rate (no UI owner).
- Design decisions table in `docs/current_architecture.md`.

## Remaining AudioEngine touch points in MainWindow

Intentionally left (orchestration / device / timecode / media):

- `set_song` / `set_song_timebase` / `set_duration` / `set_buffer`
- `apply_audio_settings` / `quiesce_output` / `ensure_playback_ready` / `rebind_playback_samples`
- `refresh_video_clips` / `set_video_track_muted` / video decode flags
- LTC/MTC status, sync offset, MIDI shutdown
- Signal subscriptions (`playing_changed`, `position_changed`, …) for UI observers
- Position/duration **reads** for monitors (clock source of truth remains engine)

## Remaining playback technical debt

- Full `_activate_song` extract (ShowSession / activate service — not this sprint task)
- RemoteHost + sync-calib still call `engine.set_music_muted` directly
- Position/duration reads still often go to `engine` instead of `playback`
- `ports.SongSession` Protocol unused for activate/refresh
- Loop still touches `_loop_engage` via façade (engine API gap)

## Risks

- Loop engage private field still set from service (same as prior MainWindow)
- Dual observers: engine signals + session mirror if sync skipped on a path
- Broader “no direct engine” wording vs intentional activate/device exceptions

## Tests

- Targeted: **8 passed** (playback service + A–B loop)
- Full suite: **900 passed**, **16 failed** (same pre-existing / Linux env set)

## Suggested next task

Sprint 2 Task 7 — SettingsService foundation (READY FOR SETTINGS SERVICE).
