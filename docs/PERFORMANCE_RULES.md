# CuePlayer — Performance Rules

**Status:** Sprint 8 Task 2 Round 8 (post-land submit + playback lateness)  
**Updated:** 2026-08-05  
**Related:** [`playback_performance_audit.md`](playback_performance_audit.md), [`video_sm_freeze_diagnosis.md`](video_sm_freeze_diagnosis.md)

---

## Non-negotiables

1. **`AudioEngine` sample position is the sole playback clock.**  
   Video, Timeline playhead, Clean Output, and Web Remote must follow it — never a second independent video/timer clock for show sync.

2. **Never put diagnostics, logging, locks, or allocations on the real-time audio callback path.**  
   Optional timing (`cueplayer.diagnostics.perf`) may run on:
   - Qt UI thread (position fan-out, paint, song activate)
   - Background worker threads (audio decode / cache load / **video live decode**)  
   Not inside PortAudio / engine callback code.

3. **Optimize only with measured evidence.**  
   No speculative Timeline / AudioEngine / video-sync redesigns in a perf PR without spans from `CUEPLAYER_PERF=1` (or an equivalent measurement).

4. **Do not change playback semantics** while measuring (seek, loop, Song↔Variant mapping, quiesce-on-song-switch safety).

5. **Feature flags for unfinished UX** must hide entry points only — never delete domain / persistence / tests.

6. **Video live decode must not stall Timeline/Playhead.**  
   Play + scrub-cold use latest-wins async decode (dedicated worker decoders). UI presents prepared frames. Scrub release uses exclusive async final-land (never UI-thread PyAV).

7. **Final-land owns the schedule until decoder position is established.**  
   Engine play requests must not overwrite `kind=land`. After land, resume continuous play (or stay paused) without a second freeze.

8. **Scrub preview must present while dragging (Round 6).**  
   Mouse moves update `latest_target` only — do not bump scrub session generation.  
   In-flight preview completes unless the pointer jumps far (≥2 s). Present within ~0.75 s tolerance.  
   Engine Video is gated during `SCRUB_PREVIEW`. Playing release: `resume_required == resume_started == resume_completed + resume_recovered`.

9. **Post-land play must submit immediately (Round 8).**  
   `FINAL_LAND_PRESENT` while `pre_scrub_was_playing` submits exactly one play decode.  
   Do not rely on incidental engine fan-out / throttle to wake playback.  
   PLAYBACK / RESUME: do **not** bump `_async_req_gen` on ordinary clock ticks;  
   keep one pending-latest target while busy; present if within ~0.35 s lateness.  
   Scrub begin / song change still invalidate. `playback.frame_drop.reason.generation_mismatch`  
   must stay ~0 for ordinary clock advancement.

10. **Deterministic seek + no empty black (Round 8b).**  
    Scrub land frame stays visible while playback decoder PREPARING.  
    Keyframe seek + decode-forward with deadline; recreate play decoder once on stall.  
    `set_song` with Video must not clear to empty widget before first poster/land.  
    `video.display_source` tracks last_valid / poster / final_land / playback_frame.

11. **Dense Marks must not starve Video (position fan-out).**  
    Mark lookup is O(log n) (bisect). Paint only visible-time Marks.  
    NOW/Cue List update only when the active Cue changes.  
    Measure sparse vs dense with `ui.position_fanout` sub-spans — see
    [`dense_mark_perf.md`](dense_mark_perf.md). Do not change Video decoder for this.

12. **Dense Mark A/B dumps must pass LIVE CHECK.**  
    Prefer Tools → Write Performance Report after play/scrub.  
    If `ui.position_fanout.calls=0`, the dump is invalid — do not interpret.  
    Scrub chrome must share fan-out spans with the engine play path.  
    See [`dense_mark_instrumentation_fix.md`](dense_mark_instrumentation_fix.md).

13. **`video.seek.frames_to_target` is GOP decode-forward, not Mark cost.**  
    Keyframe seek then decode to target; ~88 frames ≈ multi-second H.264 GOP.  
    Use `video.seek.keyframe_distance_s` before blaming the decoder.

---

## Enabling diagnostics

```powershell
# PowerShell — environment variable for this session
$env:CUEPLAYER_PERF = "1"
# Optional: custom log path
# $env:CUEPLAYER_PERF_LOG = "C:\Users\User\Desktop\cueplayer_perf.log"

cd C:\Users\willy\Projects\CuePlayer_v2   # your clone path
git fetch origin
git checkout cursor/sprint8-perf-instrumentation-fix-028d
git pull
.\.venv\Scripts\python.exe -m cueplayer.app
```

**Default log file (Windows):**  
`%LOCALAPPDATA%\CuePlayer\cueplayer_perf.log`  
(example: `C:\Users\<you>\AppData\Local\CuePlayer\cueplayer_perf.log`)

When enabled:
- Console prints the log path at startup
- Status bar shows “Perf log updated…” after each song switch
- Tools → **Write Performance Report…** appends a manual dump (only if launched with `CUEPLAYER_PERF=1`)

In-process (tests):

```python
from cueplayer.diagnostics import perf
perf.set_enabled(True)
perf.clear()
# … exercise UI …
print(perf.report_text())
print(perf.flush_report(label="manual"))
```

When disabled (default), `span` / `count` are near-zero-cost no-ops.

---

## Cadence constants (code inventory)

| Path | Interval | Notes |
|------|----------|--------|
| `AudioEngine` position poll | **16 ms** (~60 Hz) | Qt timer → `position_changed` |
| Timeline playhead repaint | **~33 ms** (~30 Hz) | While playing; dirty-region preferred |
| Timeline `view_changed` while playing | **~66 ms** | Overview / dependents |
| Video live decode schedule | **30 Hz** (24 Hz if Video Track heavy) | **Async worker** (latest-wins); UI only presents |
| Scrub live decode schedule | **24 Hz** max | Cache hit = posters; cold = async coalesce |
| Audio load poll | **25 ms** | Pending worker apply |

---

## Experimental features flag

Restore Align Anchors / MA Preflight Tools entries by setting `ENABLE_EXPERIMENTAL_FEATURES = True` in `cueplayer/features.py`. Export Preflight gate is unaffected.
