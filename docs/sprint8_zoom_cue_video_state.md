# Sprint 8 follow-up — Static render parity / low-overhead PERF / resume recovery

**Branch:** `cursor/sprint8-zoom-cue-video-state-028d`  
**Base:** `cursor/sprint8-cached-timeline-poster-028d` (PR #239)  
**PR:** #240  
**Status:** Ready for Windows STATIC RENDER / LOW-OVERHEAD PERF / RESUME RECOVERY validation  
**(do not merge #239/#240 until Windows validation passes)**

Does not change: AudioEngine / sample clock, Mark Cue timestamps, Export, Video Preview state matrix, decoder architecture, GPU decode, normal ~0.3 s seek latency budget, Mark lookup / Cue List further optimization.

## Commits on #240 (latest three)

1. **Static Timeline render parity** — PLAYING / PAUSED / STOPPED share one native retained static path; video header caption always paints; video-clip bake quality no longer depends on transport; play/pause pixel regression (mask playhead only).
2. **Low-overhead PERF** — position tick no longer calls `perf.snapshot()`; `get_attr` + bounded span rings; output TC `setStyleSheet` / font-fit skip when unchanged.
3. **Resume recovery invariant** — RESUME→PLAYBACK / READY only after current-generation playback frame presented; no false-ready on second watchdog; too_late / gen mismatch keep land + resubmit + armed watchdog; idle RESUME resubmits current target; recovery_started == recovery_completed after frame.

## Prior kept work on this PR

| Item | Notes |
|------|--------|
| Zoom screen-space annotations | kept |
| Cue List O(1) follow | do not re-optimize |
| Scrub native blit / Note layout | kept |
| Post-seek land stage bounds (~0.3 s normal) | keep; this patch targets multi-second incomplete recovery |

## Windows validation

```powershell
$env:CUEPLAYER_PERF = "1"
cd C:\Users\willy\Projects\CuePlayer_v2
git fetch origin
git checkout cursor/sprint8-zoom-cue-video-state-028d
git pull
.\.venv\Scripts\python.exe -m cueplayer.app
```

### A. Static render parity
- Same viewport/zoom; alternate PLAYING ↔ PAUSED/STOPPED
- Mark text/lines + waveform visually identical
- No dot artifacts appear/disappear

### B. Dense seek recovery
- During play: sparse → dense → sparse → dense; stay ≥10 s each
- Video continues in Dense region
- Every RESUME_BEGIN → FIRST_PLAYBACK_FRAME_PRESENTED
- `resume_recovery_started` == `resume_recovery_completed`
- No `first_valid_frame_after_seek` delay above ~1 s (multi-second freeze eliminated)

### C. PERF overhead
- Same interaction with PERF off then on — UX close
- New 5 s cProfile with PERF on: `_perf_note_position_tick` / `perf.snapshot` must not be a major hotspot
- Tools → Write Performance Report for the new session

### D. Preserve
- Audio / sample clock, zoom anchor, Zoom/Video responsiveness, Mark/Cue timestamps, Preview state matrix, Export

READY FOR WINDOWS STATIC RENDER / LOW-OVERHEAD PERF / RESUME RECOVERY VALIDATION
