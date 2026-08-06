# Sprint 8 follow-up — Backward Final Land / Video Audio continuity

**Branch:** `cursor/sprint8-zoom-cue-video-state-028d`  
**Base:** `cursor/sprint8-cached-timeline-poster-028d` (PR #239)  
**PR:** #240  
**Tip context:** after `eb935e2` Windows gate  
**Status:** Ready for Windows BACKWARD FINAL-LAND / VIDEO-AUDIO CONTINUITY validation  
**(do not merge #239/#240; do not claim Video P0 solved)**

Preserved: Timeline mouse/static visuals, AudioEngine sample clock, Mark/Cue
timestamps, Export, Preview states, zoom anchor, no GPU / broad decoder redesign.

## Confirmed still good (do not regress)

- Resume emit/ack parity; first-present ~122ms mean
- Stable PLAYBACK decode ~22–24 Hz (not ~51 Hz)

## A — Backward click never reached Final Land

Trace: SCRUB_PREVIEW_REQUEST → WAITING_FRAME → **no** SCRUB_PREVIEW_PRESENT /
FINAL_LAND_REQUEST / RESUME_BEGIN. Root cause: scrub finalize depended on a
single `mouseReleaseEvent`.

**Fix:** idempotent `_end_scrub_once`; scrub-timer + move + window-deactivate
fallback when LeftButton is up; Final Land owned by release (does not wait for
preview present). Traces: `TIMELINE_SCRUB_PRESS/RELEASE/FALLBACK_RELEASE`,
`END_SCRUB_CALLED`, `FINAL_LAND_REQUEST` (+ scrub transaction id).

## B/C — Video Audio was the stutter owner; reverse priority removed

cProfile: `_decode_window` ~2.86s / 5s; callback interval max ~724ms with VA
windows on the miss. `set_defer_live_decode(engine.video_audio_decoding)` held
Video frames during VA decode — **removed** (`set_defer_live_decode(None)`).

## D — Realtime callback is read-only

`chunk_at` only snapshots/mixes cache (silence on miss). No executor / av.open /
resample from the PortAudio path. `schedule_for_song_time` runs from
`AudioEngine._emit_position` (poll).

## E — Quantized windows + true LRU

Heavy windows on a 9s grid (12s length); coverage-hit suppresses duplicate
decodes; LRU of 8 (no 36s-behind prune); mute + SCRUB/LAND/RESUME suspend
scheduling/chaining.

## Windows validation

1. Video Audio **unmuted**: forward through dense → ~1018s → left-click back to
   ~947.8 → wait 10s.
2. Repeat **muted**.

Pass if: always `FINAL_LAND_REQUEST`; never stuck in `SCRUB_PREVIEW` after
LeftButton up; Video resumes; unmuted ≈ muted smoothness; no ~724ms callback
gaps; VA does not defer Video; ~24 Hz play decode; AudioEngine unchanged.

READY FOR WINDOWS BACKWARD FINAL-LAND / VIDEO-AUDIO CONTINUITY VALIDATION
