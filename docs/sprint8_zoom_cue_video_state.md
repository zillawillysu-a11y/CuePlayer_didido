# Sprint 8 follow-up — Zoom visual / Dense Cue follow / Video state

**Branch:** `cursor/sprint8-zoom-cue-video-state-028d`  
**Base:** `cursor/sprint8-cached-timeline-poster-028d` (PR #239)  
**PR:** #240  
**Status:** Ready for Windows UX + PERF validation (do **not** merge #239/#240 until this passes)

Does not change: AudioEngine / sample clock, Mark Cue timestamps, Export, Video seek SM direction, decoder architecture, GPU decode.

## Commits on #240

1. **Zoom / Cue / Video state** (`349e28d`) — screen-space annotations, Cue List O(1) follow, Preview states  
2. **Interaction render parity** (`dc1677e+`) — scrub native blit, first-wheel no flash, canonical Note layout  
3. **Post-seek Video stall** — land/scrub-preview bounded decode deadlines, stage telemetry, tick-interval baseline fix  

## Windows-confirmed KEPT

| Item | Evidence |
|------|----------|
| Zoom no longer freezes Video | prior #239/#240 validation |
| Cached Mark paint | mark.paint_ms ~0.61 |
| Cue List cheap | position_sync_ms mean 0.04 / max 0.84; not in cProfile top 40 |

Do **not** further optimize Cue List / Mark lookup in this patch.

## COMMIT 1 — Interaction render parity

- Scrub keeps retained native cache (no invalidate on press/release).
- Native 1:1 device-pixel blit (no dest W×H resample → no thinner text/dots).
- First wheel after scrub seeds from retained spatial cache (no blank center flash).
- Zoom Notes use same under-ruler layout as static bake (no beside↔below jump).

## COMMIT 2 — Post-seek Video worker stall

Proven stage owner from prior evidence: **decode-forward inside `video.decode.async`**, with **queue_wait** behind stale scrub-preview.

Bounded correction:
- scrub_preview decode deadline **0.30 s**
- final-land decode deadline **0.45 s**
- RESUME skips stacked second 1.5 s seek recovery
- Stage telemetry: `video.land.stage.*` + `dominant` + request_id / song / media time
- True `video.present.queue_delay_ms` = emit→UI
- `perf.position_tick_interval_ms` rejects >5 s / session-reset gaps

## Windows validation

```powershell
$env:CUEPLAYER_PERF = "1"
cd C:\Users\willy\Projects\CuePlayer_v2
git fetch origin
git checkout cursor/sprint8-zoom-cue-video-state-028d
git pull
.\.venv\Scripts\python.exe -m cueplayer.app
```

1. LMB press/release — static Timeline pixels identical (only playhead may change)  
2. Seek then one wheel notch — no center flash; no Note jump  
3. Play + zoom 10 s — Video responsive; fixed text size; Notes stable  
4. Play + seek into dense Marks — Video resumes ≤ ~300–400 ms; report land stage dominant + ready-to-present  
5. Video states — no Loading on no-video / pre-clip gap; no stale cross-song frame  

READY FOR WINDOWS INTERACTION RENDER PARITY / POST-SEEK VIDEO STALL VALIDATION
