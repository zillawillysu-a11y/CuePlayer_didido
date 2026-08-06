# Sprint 8 follow-up — Resume WAITING_FRAME liveness / mouse static parity

**Branch:** `cursor/sprint8-zoom-cue-video-state-028d`  
**Base:** `cursor/sprint8-cached-timeline-poster-028d` (PR #239)  
**PR:** #240  
**Status:** Ready for Windows RESUME LIVENESS / MOUSE STATIC PARITY validation  
**(do not merge #239/#240 until Windows validation passes)**

Does not change: AudioEngine / sample clock, Mark timestamps / Cue semantics, Export, Preview state matrix, zoom anchor, edge-Mark overlap, ~0.3 s normal seek budget, GPU decode / decoder redesign.

## Root cause (A) — WAITING_FRAME self-cancel

Dense seek decoded a play frame into `WAITING_FRAME` (queued Qt slot). Resume watchdog then treated the lack of *presented* frame as failure, called `_invalidate_async_requests()` (gen++), and submitted a replacement. The queued UI callback arrived with a stale generation and was dropped. Repeat → permanent freeze (`recovery_started=1`, `recovery_completed=0`).

## Fix (A)

- WAITING_FRAME / in-flight / pending-latest count as **active progress** → watchdog **defers** (no gen bump).
- At most **one** decoder recreate per resume transaction.
- Bootstrap: accept first resume play frame even if Audio clock advanced during UI delay; then catch up.
- Telemetry: `resume_watchdog_deferred_for_waiting_frame`, `resume_waiting_frame_presented`, queued gen/req/age, terminal status.
- Regression: delay UI present past watchdog deadline; prove no gen loop + frame presents + recovery balances.

## Fix (B)

- `_can_use_static_backdrop()` stays True for mark drag / box select / clip drag|trim.
- Only geometry edits (resize / gain drag) leave the retained blit path.
- Pixel tests: idle / LMB-down / drag / release; Video lane strip must not change on press.

## Windows validation

```powershell
$env:CUEPLAYER_PERF = "1"
cd C:\Users\willy\Projects\CuePlayer_v2   # or your clone path
git fetch origin
git checkout cursor/sprint8-zoom-cue-video-state-028d
git pull
.\.venv\Scripts\python.exe -m cueplayer.app
```

### A. Dense resume
sparse→dense→sparse→dense ×5, ≥10 s in each dense section. Pass if Video always continues; no WAITING_FRAME gen-bump loop; `resume_started==resume_completed` (plus recovered); `recovery_started==recovery_completed`.

### B. Mouse visual
Fixed viewport: mouse-up / LMB held / drag / release. Pass if no black strip pop, Video name does not appear only on mouse-down, static layers identical.

READY FOR WINDOWS RESUME LIVENESS / MOUSE STATIC PARITY VALIDATION
