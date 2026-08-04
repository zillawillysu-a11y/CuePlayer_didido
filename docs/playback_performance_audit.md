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

## 7b. Windows validation — Video responsiveness (Task 2)

```powershell
$env:CUEPLAYER_PERF = "1"
git checkout cursor/sprint8-video-responsive-028d
git pull
.\.venv\Scripts\python.exe -m cueplayer.app
```

| Scenario | What to feel / record |
|----------|------------------------|
| No-video playback | Timeline drag + playhead smooth (baseline) |
| Video playback | Playhead still smooth; Preview near source FPS; check `video.decode.async` vs `ui.position_fanout` |
| Aggressive timeline drag (Video Track on) | Pointer follows scrub; Preview may lag at ≤24 Hz; **no** UI freeze |
| Scrub release | Final frame matches release Song Time |
| Song switch | Selection + timeline paint before ~150–180 ms quiesce wait |
| CPU | Task Manager while dragging with video — UI thread should not peg from PyAV |
| Counters | `video.async_coalesce` rises under drag; `video.async_stale_drop` on scrub-end |

Fill before/after from `%LOCALAPPDATA%\CuePlayer\cueplayer_perf.log` (Tools → Write Performance Report…).

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

## 10. Sprint 8 Task 2 — Video Track Responsiveness (done)

**Branch:** `cursor/sprint8-video-responsive-028d`

### Root causes confirmed

1. Live PyAV decode on the Qt UI thread during play and scrub-cold.  
2. Scrub mouse-moves could still sync-decode when the poster cache was cold.  
3. Song activate ran `quiesce_output` (~150–180 ms) before timeline chrome painted.

### Pipeline before → after

| Stage | Before | After |
|-------|--------|-------|
| Play tick | Throttle → UI `_decode_and_emit` | Throttle → async latest-wins worker |
| Scrub warm | Poster emit (UI) | Unchanged |
| Scrub cold | Throttle → UI decode | Throttle → async coalesce |
| Scrub-end / stop | Sync land | Sync land (gen invalidate first) |
| Present | QImage on UI | Same; spans `video.convert` / `video.present` |
| Song switch | Quiesce → timeline | Stop → timeline → paint → quiesce |

### UI-thread work removed

- Mid-play PyAV seek/decode/colorspace  
- Mid-scrub cold PyAV (replaced by worker)

### Request policy

- Queue depth **0 or 1** (overwrite `_async_req_seconds`)  
- `_async_req_gen` drops stale results  
- Dedicated `_worker_decoders` (never share UI land-frame decoders)

### Remaining limitations

- Scrub-end / `land_frame_at` still sync-decode once (accuracy).  
- `video.convert` (ndarray→QImage) still on UI (cheap vs PyAV).  
- Quiesce wait duration unchanged (safety); only perceived order improved.  
- Warm scrub still needs poster preload after drag starts.

### Performance Impact (Task 2)

| Area | Expected |
|------|----------|
| Audio playback | Unchanged (clock / RT path untouched) |
| Timeline drag | Responsive with Video Track |
| Playhead smoothness | Improved (no UI PyAV contention) |
| Video FPS | Stable async present ≤30/24 Hz schedule |
| Song-switch feel | Immediate chrome; quiesce still ~150–180 ms after paint |
| CPU | PyAV moves to worker thread |
| Memory | +1 ThreadPool worker + optional second decoder set per clip |

---

## READY FOR WINDOWS VIDEO RESPONSIVENESS VALIDATION
