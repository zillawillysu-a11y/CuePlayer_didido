# CuePlayer — Performance Rules

**Status:** Sprint 8 Task 2 Round 4 (final-land priority + resume)  
**Updated:** 2026-08-05  
**Related:** [`playback_performance_audit.md`](playback_performance_audit.md)

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

---

## Enabling diagnostics

```powershell
# PowerShell — environment variable for this session
$env:CUEPLAYER_PERF = "1"
# Optional: custom log path
# $env:CUEPLAYER_PERF_LOG = "C:\Users\User\Desktop\cueplayer_perf.log"

cd C:\Users\User\Projects\CuePlayer_didido   # your clone path
git checkout cursor/sprint8-video-responsive-028d
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
