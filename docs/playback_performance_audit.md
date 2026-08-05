# Playback Performance Audit — Sprint 8 Task 1

**Status:** Audit + instrumentation complete (no speculative optimizations)  
**Updated:** 2026-08-04  
**Branch:** `cursor/sprint8-perf-audit-028d`  
**Rules:** [`PERFORMANCE_RULES.md`](PERFORMANCE_RULES.md)

This document is the evidence base for Tasks 2–5. Numbers below mix **code-constant analysis** with **instrumentation hooks**. Wall-clock song-switch ms on production media must be filled from a desk run with `CUEPLAYER_PERF=1`.

---

## Objective A — Experimental feature hide (done)

| Entry | Hidden when `ENABLE_EXPERIMENTAL_FEATURES is False` |
|-------|------------------------------------------------------|
| Tools → Align Anchors… | Yes (menu `addAction` skipped) |
| Tools → MA Preflight… | Yes |

- Implementation / tests / domain / persistence / docs **kept**.  
- Project schema **unchanged**.  
- Show Patch **export Preflight gate** still runs (production export safety).  
- Restore: set `ENABLE_EXPERIMENTAL_FEATURES = True` in `cueplayer/features.py`.

---

## Objective B — Instrumentation (done)

Module: `cueplayer.diagnostics.perf` (off unless `CUEPLAYER_PERF=1` / `set_enabled(True)`).

| Span / counter | Location |
|----------------|----------|
| `activate.song.total` + subspans | `ShowSessionService.activate_song_at` |
| `activate.waveform_arm` + `activate.waveform_path` attr | `_prepare_waveform_and_audio` (`ram_hit` / `peaks_hit` / `cold` / `standin_or_empty`) |
| `activate.monitor_deferred` | Deferred Cue List `set_song` |
| `audio.load.worker` | Background `load_audio_cached` |
| `audio.apply` / `waveform.display_build` | `_apply_loaded_audio` |
| `ui.position_fanout` + calls counter | `MainWindow._on_position_changed` |
| `timeline.set_position.calls` / `timeline.paint.*` | `TimelineWidget` |
| `video.update_position.calls` / `video.decode` / `video.decode.async` | `VideoSyncController` |
| `video.async_schedule` / `video.async_coalesce` / `video.async_stale_drop` | Latest-wins request policy |
| `video.convert` / `video.present` | `MainWindow._on_video_frame` (QImage + sinks) |
| `activate.stop` / `activate.paint_before_quiesce` | Soft-stop + paint before stream teardown |

**Not instrumented (by design):** PortAudio callback / any RT audio path.

---

## 1. Song-switch timing breakdown

### Measured architecture (sync UI-thread order)

```text
activate.song.total
  ├─ activate.stop                 engine.stop (soft; if needs quiesce)
  ├─ activate.arm_placeholder      Music lane "Loading…"
  ├─ activate.timeline             timeline.set_song + mark-line chrome
  ├─ activate.paint_before_quiesce processEvents (ExcludeUserInput) — perceived switch
  ├─ activate.quiesce              engine.quiesce_output (PortAudio teardown ~150–180ms)
  ├─ activate.video_bind           video_sync.set_song (close/open decoders)
  ├─ activate.engine_attach        engine.set_song + timebase
  ├─ activate.geometry_chrome      geometry, shortcuts, TC clock
  ├─ activate.waveform_arm         RAM / peaks / cold / stand-in
  │     ├─ ram_hit  → audio.apply (sync, playback-ready immediately)
  │     ├─ peaks_hit → paint peaks; worker PCM load
  │     └─ cold → Loading…; worker PCM + peaks
  ├─ activate.chrome               title, status, overview
  └─ activate.video_land           ensure preview frame (may decode)
+ QTimer(0) → activate.monitor_deferred   Cue List rebuild (after first paint)
+ worker → audio.load.worker → audio.apply (async path)
```

### Desk measurement template (`CUEPLAYER_PERF=1`)

| Metric | How to read |
|--------|-------------|
| Time to waveform visible | End of `activate.waveform_arm` on `ram_hit`/`peaks_hit`; else first `timeline.set_audio` after worker |
| Time to audio buffer ready | `audio.apply` after worker (or sync on `ram_hit`) |
| Time to playback-ready | `audio.playback_ready` note + `engine.buffer` armed |
| UI-thread activate cost | `activate.song.total` (excludes worker decode) |

**Fill on site (example table):**

| Song | Path | `activate.song.total` ms | waveform_path | `audio.load.worker` ms | Notes |
|------|------|--------------------------|---------------|------------------------|-------|
| | | | | | |

---

## 2. UI-thread blocking operations

| Operation | Thread | Risk |
|-----------|--------|------|
| `activate.song.total` body | UI | High if cold media / video land / monitor not deferred |
| `timeline.set_song` / full paint | UI | Medium–high on dense shows |
| `video_sync.set_song` / `land_frame_at` | UI | High with Video Track + large files |
| `monitor.set_song` (deferred) | UI | Medium (Cue List) |
| `load_audio_cached` | **Worker** | OK; hitch if mis-called on UI (guarded: RAM-only sync) |
| `probe_audio_duration` on arm | UI | Low–medium (metadata only) |
| `ui.position_fanout` @ ~60 Hz | UI | Must stay cheap (already avoids double overview sync) |
| `video.decode` (PyAV land / pause) | UI | One-shot only (scrub-end / stop / land) |
| `video.decode.async` (PyAV live) | **Worker** | Play + scrub-cold; latest-wins |
| `video.convert` / `video.present` | UI | QImage + Preview/Clean paint |

---

## 3. Video Track bottlenecks

### Before (Task 1 desk finding)

1. **Decode on Qt UI thread** — `_decode_and_emit` ran PyAV on every throttled play/scrub tick.  
2. **Throttle 30 Hz / 24 Hz** still competed with Timeline paints when Video Track was open.  
3. **Frame fan-out** — Preview + Clean Output QImage conversion on emit.  
4. **Scrub cold path** — mouse-move could still sync-decode when scrub posters were cold.  
5. **Song switch** — `activate.quiesce` (~150–180 ms) ran **before** timeline chrome painted.

### After (Task 2)

1. **Play + scrub-cold** → `_request_async_live_frame` (single worker, dedicated decoders, queue depth 1).  
2. **Scrub warm** → scrub-cache posters on UI (cheap).  
3. **Scrub-end / pause land / `land_frame_at`** → one-shot sync decode for accuracy.  
4. **Stale results** dropped via `_async_req_gen`; coalesce counted as `video.async_coalesce`.  
5. **Song switch** → soft `stop` + timeline paint + `processEvents` **before** `quiesce_output`.  
6. **Presentation spans** — `video.convert` / `video.present` separate from decode.

---

## 4. Playhead repaint / update analysis

| Stage | Rate | Work |
|-------|------|------|
| Engine poll | 16 ms | Emit Variant Time (not RT callback) |
| `_on_position_changed` | ~60 Hz | Song-time map + timeline/transport/monitor/clock |
| `timeline.set_position` while playing | repaint ≤ ~30 Hz | Dirty playhead region preferred; full update on scroll follow |
| `paintEvent` | On dirty | Static backdrop blit + playhead; full rebuild only when backdrop invalid |

**Finding:** Playhead path is already cadence-limited; remaining risk is **full-widget updates** when auto-scroll moves or backdrop invalidates, especially with Video Track height.

Counters: `timeline.set_position.calls`, `timeline.paint.partial` / `.full`.

---

## 5. Waveform cache analysis

| Layer | Sync on UI? | Role |
|-------|-------------|------|
| RAM `_audio_buffer_cache` | Yes (dict hit) | Instant `ram_hit` → apply |
| Disk peaks sidecar | Sync read (small) | Instant lane paint; PCM still async |
| Disk full `.npz` / decode | Worker | `audio.load.worker` |
| Display LTC-stripped cache | Sync build on apply | `waveform.display_build` |

**Finding:** Warm RAM path is the gold path for “immediate waveform + playback.” Cold path shows Loading… until worker finishes — expected; measure worker ms on real WAVs.

Attr: `activate.waveform_path` ∈ {`ram_hit`,`peaks_hit`,`cold`,`standin_or_empty`}.

---

## 6. Ranked bottleneck list (audit priority)

| Rank | Bottleneck | Evidence | Suggested task |
|------|------------|----------|----------------|
| **1** | Cold / peaks song-switch until PCM ready | Worker gate; UI waits for play | Task 2 — readiness / prefetch |
| **2** | UI-thread video decode under play | `video.decode` on UI; 24–30 Hz | Task 3 — video offload / budget |
| **3** | `activate.video_land` + decoder teardown on switch | Sync in activate total | Task 2/3 |
| **4** | Deferred Cue List still heavy | `activate.monitor_deferred` | Task 4 — monitor cost |
| **5** | Full Timeline paints with Video Track | `timeline.paint.full` under scroll | Task 5 — paint isolation |
| **6** | Position fan-out @ 60 Hz | Cheap today; watch regressions | Guardrails only |

---

## 7. Implementation plan — Tasks 2–5

| Task | Goal | Status |
|------|------|--------|
| **2 — Video Track responsiveness** | Off-UI latest-wins decode; paint before quiesce | **Done** (this PR) |
| **3 — Further video budget** | Optional QImage off-UI; sink skip polish | Next if desk still shows convert cost |
| **4 — Cue List / chrome** | Shrink `activate.monitor_deferred` | Pending |
| **5 — Playhead / paint** | Keep partial dirty; reduce full paints | Pending |

Each task PR must include before/after `CUEPLAYER_PERF` spans on the same show file.

---

## 7b. Windows validation — Video responsiveness Round 2

```powershell
$env:CUEPLAYER_PERF = "1"
cd C:\Users\User\Projects\CuePlayer_didido
git fetch origin
git checkout cursor/sprint8-video-responsive-028d
git pull origin cursor/sprint8-video-responsive-028d
.\.venv\Scripts\python.exe -m cueplayer.app
```

**Must see at startup / Tools → Write Performance Report:**

- `video.pipeline_mode: async_latest_wins`
- `perf.session_id: …`
- After play with video: `video.decode.async` and/or `video.async_schedule` &gt; 0
- Prefer **last** `=====` section only (log appends history)

| Scenario | Pass criteria |
|----------|----------------|
| A/B same song, Video Track on vs off | Drag + playhead feel nearly the same |
| Play 20 s with video | `ui.position_fanout` mean &lt; 3 ms; no multi-second `video.decode.sync` |
| Aggressive scrub | Partial scrub playhead requests dominate; Preview may lag ≤24 Hz |
| Scrub release | Exact land frame; `video.async_stale_drop` OK |
| Counters | `video.schedule.source.engine` during play; `.scrub` only while dragging |

---

## 7c. Windows validation — Live scrub preview Round 3

```powershell
$env:CUEPLAYER_PERF = "1"
cd C:\Users\User\Projects\CuePlayer_didido
git fetch origin
git checkout cursor/sprint8-video-responsive-028d
git pull origin cursor/sprint8-video-responsive-028d
.\.venv\Scripts\python.exe -m cueplayer.app
```

**Scrub preview target:** 16 FPS (`video.scrub.preview_target_fps`)

| Test | Pass |
|------|------|
| Slow drag across a cut | Preview visibly follows during drag |
| Fast back/forth | Timeline stays fluid; video skips but updates toward latest |
| Drag + pause (hold) | Preview settles on paused location without release |
| Release on recognizable frame | Relevant frame ASAP; exact land quickly; no old-frame flash |
| Play after release | Continues from release time; no stale pre-scrub flash |
| vs no-video | Timeline hand feel nearly identical |

**Log counters to check (last section only):**
`video.scrub.raw_position_events`, `preview_ticks`, `preview_requests`,
`preview_presented`, `preview_coalesced`, `pause_priority_requests`,
`final_land_requests`, `final_land_presented`, spans
`video.scrub.final_land_first_relevant_ms` / `final_land_exact_ms`.

---

## 8. Baseline performance test checklist

Run on Windows desk with production interface:

- [ ] Cold start → open large show → switch song (cold) → record report  
- [ ] Warm switch (second visit / RAM hit) → report  
- [ ] Peaks-only restart (kill app, reopen) → waveform visible before PCM  
- [ ] Play 30 s, Auto Scroll on/off → `timeline.paint.full` vs `.partial`  
- [ ] Same song **without** Video Track vs **with** clips + Clean Output  
- [ ] Add Video Track mid-session → note UI sluggishness / decode spans  
- [ ] Confirm `AudioEngine` still sole clock (video follows playhead)  
- [ ] Confirm no new logging in audio callback (code review)  
- [ ] Experimental menus still hidden (`ENABLE_EXPERIMENTAL_FEATURES=False`)  
- [ ] Existing pytest green (`test_experimental_features_hide`, `test_perf`, song-switch tests)

---

## 9. Performance Impact (Task 1 audit PR)

| Area | Impact |
|------|--------|
| **Playback** | None intended — semantics unchanged; diagnostics off by default |
| **Timeline FPS** | Negligible when `CUEPLAYER_PERF` off |
| **Song switch** | Same paths; optional spans only when enabled |
| **Video sync** | Same clock / throttle; decode wrapped only when enabled |
| **CPU** | ~0 when disabled; mild when enabled during play |
| **Memory** | Span lists grow until `perf.clear()` |

---

## 10. Sprint 8 Task 2 — Video Track Responsiveness

**Branch:** `cursor/sprint8-video-responsive-028d`

### Round 1 desk result — incomplete

~50% better; not acceptance. Uploaded log lacked `video.decode.async` /
`video.convert` / `video.present` / coalesce counters.

**Why those metrics were missing:**

1. Sync land/scrub-end used span name `video.decode` (desk mean ~35 ms, max ~2391 ms
   under `av_path_lock` cold acquire).
2. Perf log **appends**; older Task 1 sections have no Task 2 names.
3. Warm scrub posters emit without decode spans; async counters only when scheduled.
4. Report did not force-list expected video keys at 0.

### Round 2 root causes + fixes

| Finding | Cause | Fix |
|---------|-------|-----|
| Lag vs no-video | Queued `position→video` backlog + full scrub paints | Single fan-out schedule; scrub partial dirty |
| video.update &gt; timeline.set_position | Scrub skips `set_position` but still updates video (expected) + Queued pile | `source=engine|scrub` counters; no Queued forward |
| Full paints | Scrub `update()` + eager backdrop invalidate every move; overview 2× | Partial playhead; throttle view_changed; no preview overview sync |
| 2391 ms decode | Cold `lock.acquire()` wait | `lock_timeout` on worker + sync land; async fallback |

### Active pipeline

`video.pipeline_mode: async_latest_wins` (always in report). Play/scrub-cold worker;
scrub-end/stop sync land with timeout.

### Remaining limitations

- Auto-scroll still needs full viewport blit when scroll moves (content must shift).
- `video.convert` still on UI (lighter than PyAV).
- Quiesce duration unchanged.
- Exact land may be limited by GOP/keyframe distance on some codecs; Round 3
  shows nearest relevant immediately, then exact when ready.

### Round 3 — live scrub preview + fast final-land

| Policy | Behavior |
|--------|----------|
| Drag | `scrub_target_changed` every move; ~16 Hz preview timer + pause-priority |
| Queue | Depth 1 latest-wins; stale gen dropped |
| Release | Invalidate gen → nearest poster → **async exact land only** (no UI sync try) |
| Resume | `_min_present_seconds` rejects pre-release frames |

### Round 4 — final-land priority + continuous resume

**Windows Round 3 failure:** `final_land_exact_ms` mean ~1132 ms / max ~4690 ms;
only 9/16 lands presented; after correct frame, Video froze again.

| Root cause | Fix |
|------------|-----|
| Engine resumed before land → queue-depth-1 play overwrote land | `FINAL_LANDING` gates engine; play cannot replace `kind=land` |
| `scrub_ended` ran `end_scrub` before video finalize | MainWindow: video `set_scrubbing(False)` **before** `end_scrub` |
| Land `None` (lock timeout) left `_scrub_land_pending` stuck | Retry land; land uses `stale_on_timeout=False` |
| No explicit resume transition | `RESUME_PLAYBACK` → accept engine → `PLAYBACK` after first valid frame |
| Unrelated pre-scrub freeze on release | Immediate preview/poster; else neutral pending |

**Pipeline:** `PLAYBACK` → `SCRUB_PREVIEW` → `FINAL_LANDING` → `RESUME_PLAYBACK` → `PLAYBACK`

**New diagnostics:** `video.pipeline_state`, `final_land_superseded`,
`final_land_cache_hit/miss`, `final_land_worker_queue_wait_ms`,
`final_land_decode_ms`, `engine_requests_blocked_during_land`,
`final_land_overwritten_attempts`, `resume_*`, `min_present_seconds_*`.

---

## 7d. Windows validation — Final-land + resume Round 4

```powershell
$env:CUEPLAYER_PERF = "1"
cd C:\Users\User\Projects\CuePlayer_didido
git fetch origin
git checkout cursor/sprint8-video-responsive-028d
git pull origin cursor/sprint8-video-responsive-028d
.\.venv\Scripts\python.exe -m cueplayer.app
```

| Test | Pass |
|------|------|
| A — scrub while playing | Relevant/exact quickly; continuous play from release; **no second freeze** |
| B — scrub while paused | Landed frame stays; Play starts immediately from release |
| C — repeat 10× | No stuck `FINAL_LANDING`; no stale flash |

**Log checks:** `final_land_presented` ≈ `final_land_requests` (minus superseded);
`final_land_exact_ms` not multi-second; `resume_completed` after play-scrub;
`engine_requests_blocked_during_land` > 0 when releasing mid-play;
`video.pipeline_state` returns to `PLAYBACK`.

### Round 5 — empty decode, target resolution, bounded recovery

**Windows Round 4 failure:** `release_target_media_time=None`,
`final_land_cache_miss=170` / `retry=163` / `completed=0`,
`async_empty_keep_last=173`, accidental black during drag, >10 s freeze.

| Root cause | Fix |
|------------|-----|
| Gap/out-of-range release still scheduled land with None media time | `_resolve_release_target` → explicit `VALID`/`GAP`/`OUT_OF_RANGE`/`MISSING`/`INVALID`; no land decode for non-valid |
| `_emit_frame(None)` on gap / miss | Keep last valid unless intentional `allow_clear`; reject zero-size |
| `_LAND_MAX_RETRIES=120` (~2 s+) | Cap ≤5 retries and 500 ms deadline; exit FINAL_LANDING safely |
| resume_started ≠ resume_completed | Resume watchdog + complete on first post-land play frame |
| Stuck empty decoder | Bounded worker decoder reset after repeated empties |

**Retry policy after:** max 5 retries, 500 ms wall deadline, only for transient
lock/seek empties on a `VALID_MEDIA_TARGET`. Gaps/missing/invalid exit immediately.

---

## 7e. Windows validation — Empty-frame + recovery Round 5

```powershell
$env:CUEPLAYER_PERF = "1"
cd C:\Users\willy\Projects\CuePlayer_v2
git fetch origin
git checkout cursor/sprint8-video-responsive-028d
git pull origin cursor/sprint8-video-responsive-028d
.\.venv\Scripts\python.exe -m cueplayer.app
```

| Test | Pass |
|------|------|
| A slow drag | Follows; no accidental black |
| B fast back/forth | Timeline smooth; video may skip, never clears black |
| C release while playing | Relevant/exact quickly; continues; no 10 s load |
| D release while paused | Lands and stays; Play from there |
| E clip start/end/before/after/gap | Intentional; no retry storm |
| F 20× | No stuck FINAL_LANDING; resume completes when playing |

**Log checks:** `release_target_kind` always set; `final_land_retry` ≤5 per txn;
`final_land_deadline_exit` / `recoverable_failure` rare; `black_present.attempt`
only when reject; playing scrub → `resume_started` ≈ `resume_completed`.

---

## READY FOR WINDOWS VIDEO EMPTY-FRAME AND RECOVERY VALIDATION
