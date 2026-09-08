# Round 7 — Video state-machine freeze diagnosis (instrumentation only)

**Status:** diagnosis + trace only — **no pipeline redesign / no speculative fix**  
**Branch:** `cursor/sprint8-video-sm-trace-028d`  
**Related:** Sprint 8 Task 2 Round 6 tip `202055c`

## Symptom (Windows)

After scrub release:

1. Final land frame often appears correctly (`FINAL_LAND_PRESENT`).
2. Video then stays frozen for up to ~20 s before continuous play updates resume.
3. Timeline remains smooth — this is **not** an FPS / Timeline issue.

## Instrumentation added

Module: `cueplayer.diagnostics.video_sm_trace` (active when `CUEPLAYER_PERF=1`).

Canonical events (each with state, generation, worker_id, song/media time,
request_id, reason/scheduler):

| Event | Where |
|-------|--------|
| `SCRUB_PREVIEW_ENTER` | `set_scrubbing(True)` |
| `SCRUB_PREVIEW_REQUEST` | scrub preview schedule |
| `SCRUB_PREVIEW_PRESENT` | preview present |
| `FINAL_LAND_REQUEST` | `_schedule_final_land` |
| `FINAL_LAND_DECODE_BEGIN` / `DONE` | async worker land path |
| `FINAL_LAND_PRESENT` | `_complete_final_land` |
| `RESUME_BEGIN` | `_enter_resume_playback` |
| `SCHEDULE_NEXT_PLAY` | every play schedule (tagged with `scheduler=`) |
| `FIRST_PLAY_FRAME` / `PLAY_PRESENT` | play present path |
| `WORKER_RUNTIME` | IDLE/SEEKING/DECODING/WAITING_FRAME/PRESENTING/CANCELLED |
| `STALE_DROP` / `DISCARD` | reject paths |

Every line includes `worker_runtime=` and `request_id` / `cur_req=`.

**Who schedules the next play frame after `FINAL_LAND_PRESENT`:**

1. **Immediate:** `scheduler=enter_resume_playback` inside `_enter_resume_playback`
   → `_request_async_live_frame(kind="play", force=True)` at release Song Time.
2. **Continuous:** `scheduler=mainwindow_position_fanout` → `update_position(source=engine)`
   → `scheduler=update_position_playing` (only while `_playing` and not gated).
3. **Recovery:** `scheduler=resume_watchdog_recovery` if resume watchdog fires.

Perf report (`Tools → Write Performance Report…` or song-switch flush) now includes
a `VIDEO_SM` section with `LAND→FIRST_PLAY_FRAME gap_ms` and post-land
`SCHEDULE_NEXT_PLAY` lines.

Breadcrumbs are also appended live to `%LOCALAPPDATA%\CuePlayer\cueplayer_perf.log`
as `VIDEO_SM …` lines.

## Code-path note (hypothesis only — **not proven**)

Round 7 initially suspected a single-worker coalesce stall. That remains a
**candidate**, not a conclusion.

Windows VIDEO_SM is the **source of truth**. Before Round 8 changes anything,
the log must distinguish:

| Hypothesis | Evidence in VIDEO_SM |
|------------|----------------------|
| **A — worker occupied** | After `RESUME_BEGIN`, `worker_runtime` stays in `SEEKING` / `DECODING` / `WAITING_FRAME` for the freeze; `SCHEDULE_NEXT_PLAY` may continue with `reason=coalesce_worker_busy` and matching `request_id` / `current_request_id` |
| **B — scheduler stopped** | After `RESUME_BEGIN`, `worker_runtime=IDLE` and **no** (or abruptly stops) `SCHEDULE_NEXT_PLAY`; no `SEEKING`/`DECODING` for the freeze window |

Every VIDEO_SM line now includes `worker_runtime=` and `cur_req=` /
`request_id=`. `WORKER_RUNTIME` events fire on transitions:

`IDLE` → `SEEKING` → `DECODING` → `WAITING_FRAME` → `PRESENTING` → `IDLE`
(plus `CANCELLED` on generation mismatch).

Perf report also prints a local heuristic `post_land_hypothesis` — treat it as
a hint only; use the Windows log to decide A vs B.

**Do not redesign the pipeline. Do not implement Round 8 until A or B is confirmed.**

### Suspected transition patterns (to confirm)

**A:**
```text
FINAL_LAND_PRESENT
RESUME_BEGIN
SCHEDULE_NEXT_PLAY …
WORKER_RUNTIME … worker_runtime=SEEKING|DECODING req=…
SCHEDULE_NEXT_PLAY … reason=coalesce_worker_busy worker_runtime=SEEKING|DECODING
… long gap …
FIRST_PLAY_FRAME
```

**B:**
```text
FINAL_LAND_PRESENT
RESUME_BEGIN
WORKER_RUNTIME … worker_runtime=IDLE
(no SCHEDULE_NEXT_PLAY / no SEEKING|DECODING)
… long gap …
```

## Windows capture procedure

```powershell
$env:CUEPLAYER_PERF = "1"
cd C:\Users\willy\Projects\CuePlayer_v2
git fetch origin
git checkout cursor/sprint8-video-sm-trace-028d
git pull origin cursor/sprint8-video-sm-trace-028d
.\.venv\Scripts\python.exe -m cueplayer.app
```

1. Play a song with video; scrub-release while playing until the freeze reproduces.
2. Tools → **Write Performance Report…** (or check the perf log).
3. Search for `VIDEO_SM` and especially:
   - `FINAL_LAND_PRESENT`
   - `RESUME_BEGIN`
   - `SCHEDULE_NEXT_PLAY` (`scheduler=` + `reason=` + `worker_runtime=`)
   - `WORKER_RUNTIME` (`SEEKING` / `DECODING` / `WAITING_FRAME` / `IDLE`)
   - `request_id` / `cur_req=` / `current_request_id`
   - `FIRST_PLAY_FRAME` / `PLAY_PRESENT`
   - `LAND→FIRST_PLAY_FRAME gap_ms`
   - `post_land_hypothesis` (hint only)

Decide **A vs B** from that log before any Round 8 change.

## Round 8 — Confirmed fix (Windows VIDEO_SM)

Windows confirmed **Root Cause A + B**:

### A — Post-land submit gap
```text
FINAL_LAND_PRESENT
WORKER_RUNTIME … IDLE reason=after_final_land_present
SCHEDULE_NEXT_PLAY … reason=engine_fanout_post_land   (repeated)
```
MainWindow logged `engine_fanout_post_land` **before** `update_position`, which
often throttled/skipped without advancing `request_id`. Worker stayed IDLE.

**Fix:** `_enter_resume_playback` submits exactly one play decode immediately
(`post_land_submit_attempt` / `success` / `skipped_reason`). Do not force
`IDLE after_final_land_present` over an already-submitted SEEKING worker.
MainWindow no longer emits fake SCHEDULE before `update_position`; skips
report `reason=skip:…` from VideoSync.

### B — Playback generation starvation
Ordinary clock used to bump `_async_req_gen` on every play schedule →
`generation_mismatch_after_decode` → frames never presented.

**Fix — generation scopes:**
| Scope | Changes when |
|-------|----------------|
| `media_session_generation` | song / video track / clip binding |
| `scrub_transaction_generation` | scrub begin / release / new scrub |
| `playback_request_sequence` | diagnostics/order only — **does not invalidate** |

PLAYBACK / RESUME: pending-latest while busy; present if within
`_PLAYBACK_LATENESS_TOLERANCE_S` (0.35 s); drop only session change / scrub /
too late / newer already presented / real invalidate.

### Expected healthy post-land sequence
```text
FINAL_LAND_PRESENT
RESUME_BEGIN
SCHEDULE_NEXT_PLAY reason=post_land_submit_success  (request_id advances)
WORKER_RUNTIME SEEKING / DECODING / …
FIRST_PLAY_FRAME
PLAY_PRESENT …
```

`playback.frame_drop.reason.generation_mismatch` should stay ~0 for ordinary
clock advancement.

## Round 8b — Deterministic seek / handoff / no-black

Windows showed position-dependent freezes (e.g. ~90 s / ~150 s differ from
~120 s) and black Preview on activate/click even when Video exists.

| Area | Fix |
|------|-----|
| Handoff | `PLAYBACK_DECODER_PREPARING` → first play frame → `READY` / `FIRST_PLAYBACK_FRAME_PRESENTED`; keep land frame visible |
| Seek | Keyframe seek + decode-forward; `SeekTelemetry`; deadline recreate once |
| Display | `video.display_source`; `set_song` with Video does not clear to empty widget; posters on click/activate |

Expected VIDEO_SM extras: `PLAYBACK_DECODER_PREPARING`, `PLAYBACK_DECODER_READY`,
`FIRST_PLAYBACK_FRAME_PRESENTED`, plus `video.seek.*` notes in the perf report.

## STOP (Round 7 historical)

Round 7 shipped **instrumentation + diagnosis only**. Round 8 / 8b implement
the confirmed fixes without redesigning Timeline / AudioEngine.
