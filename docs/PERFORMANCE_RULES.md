# CuePlayer — Performance Rules

**Status:** Sprint 8 Task 1 (audit + experimental hide)  
**Updated:** 2026-08-04  
**Related:** [`playback_performance_audit.md`](playback_performance_audit.md)

---

## Non-negotiables

1. **`AudioEngine` sample position is the sole playback clock.**  
   Video, Timeline playhead, Clean Output, and Web Remote must follow it — never a second independent video/timer clock for show sync.

2. **Never put diagnostics, logging, locks, or allocations on the real-time audio callback path.**  
   Optional timing (`cueplayer.diagnostics.perf`) may run on:
   - Qt UI thread (position fan-out, paint, song activate)
   - Background worker threads (audio decode / cache load)  
   Not inside PortAudio / engine callback code.

3. **Optimize only with measured evidence.**  
   No speculative Timeline / AudioEngine / video-sync redesigns in a perf PR without spans from `CUEPLAYER_PERF=1` (or an equivalent measurement).

4. **Do not change playback semantics** while measuring (seek, loop, Song↔Variant mapping, quiesce-on-song-switch).

5. **Feature flags for unfinished UX** must hide entry points only — never delete domain / persistence / tests.

---

## Enabling diagnostics

```powershell
$env:CUEPLAYER_PERF = "1"
.\.venv\Scripts\python.exe -m cueplayer.app
```

In-process (tests):

```python
from cueplayer.diagnostics import perf
perf.set_enabled(True)
perf.clear()
# … exercise UI …
print(perf.report_text())
```

When disabled (default), `span` / `count` are near-zero-cost no-ops.

---

## Cadence constants (code inventory)

| Path | Interval | Notes |
|------|----------|--------|
| `AudioEngine` position poll | **16 ms** (~60 Hz) | Qt timer → `position_changed` |
| Timeline playhead repaint | **~33 ms** (~30 Hz) | While playing; dirty-region preferred |
| Timeline `view_changed` while playing | **~66 ms** | Overview / dependents |
| Video decode throttle | **30 Hz** (24 Hz if Video Track heavy) | UI-thread PyAV |
| Audio load poll | **25 ms** | Pending worker apply |

---

## Experimental features flag

```python
# cueplayer.features
ENABLE_EXPERIMENTAL_FEATURES = False  # hide Align Anchors + MA Preflight Tools menus
```

Set `True` to restore Tools entries. Export Preflight **gate** on Show Patch remains (production path).

---

## READY FOR MEASURED PERFORMANCE OPTIMIZATION
