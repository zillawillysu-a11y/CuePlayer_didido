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
| `STALE_DROP` / `DISCARD` | reject paths |

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

## Code-path diagnosis (where the pipeline stops)

**Precise freeze window:** after `FINAL_LAND_PRESENT` / `RESUME_BEGIN`, before
`FIRST_PLAY_FRAME` / continuous `PLAY_PRESENT`.

**What does *not* stop:**

- Timeline / AudioEngine clock (desk reports smooth drag + playhead).
- State transition into `RESUME_PLAYBACK` (Resume is entered from land).
- Engine fan-out after leaving `FINAL_LANDING` (`engine_video_gated()` is false
  for `RESUME_PLAYBACK` / `PLAYBACK`).

**What blocks presentation:**

CuePlayer has **one** live-decode worker (`ThreadPoolExecutor max_workers=1`,
`video-live-decode:1`). Play schedules while `_async_inflight` is true only
**coalesce** (overwrite `latest_target`) — they cannot start a second decode.

So if the worker is inside a long `video.decode.async` (land exact seek, or the
first play-decoder seek after scrub), every post-land schedule looks like:

```text
FINAL_LAND_PRESENT
RESUME_BEGIN
SCHEDULE_NEXT_PLAY scheduler=enter_resume_playback reason=submit_or_idle|coalesce_worker_busy
SCHEDULE_NEXT_PLAY scheduler=mainwindow_position_fanout reason=engine_fanout_coalesce_while_busy  (× many)
… seconds with NO FIRST_PLAY_FRAME / PLAY_PRESENT …
(FIRST_PLAY_FRAME only when the blocked worker finally finishes)
```

The resume watchdog (400 ms + 400 ms) **invalidates generation and re-requests**,
but it **cannot preempt** the in-flight PyAV seek on the same single worker.
`_complete_resume(reason="recovery")` may flip state to `PLAYBACK` without a new
frame — UI keeps showing the landed still until the worker returns.

This matches “final frame correct → frozen up to ~20 s → then updates again”
without Timeline jank: the presentation loop is waiting on the busy worker, not
on pointer/engine scheduling.

### Suspected transition (to confirm on Windows log)

```text
FINAL_LAND_PRESENT
  → RESUME_BEGIN
  → SCHEDULE_NEXT_PLAY (enter_resume_playback)
  → [worker still in FINAL_LAND_DECODE_* or long play seek]
  → SCHEDULE_NEXT_PLAY … reason=coalesce_worker_busy  (repeated)
  → gap until FIRST_PLAY_FRAME / PLAY_PRESENT
```

**Not** a missing Resume enter. **Not** engine permanently gated after land.
**Is** presentation stalled waiting for the single async worker to leave a long
decode/seek before any post-land play frame can present.

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
   - `SCHEDULE_NEXT_PLAY` (`scheduler=` + `reason=coalesce_worker_busy`)
   - `FIRST_PLAY_FRAME` / `PLAY_PRESENT`
   - `LAND→FIRST_PLAY_FRAME gap_ms`

## STOP

Round 7 ships **instrumentation + diagnosis only**. No speculative fix in this
change. Next round should use the Windows `VIDEO_SM` log to confirm the
coalesce-while-busy gap, then fix that specific stall (without redesigning
Timeline / AudioEngine).
