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
| `video.update_position.calls` / `video.decode` / `video.emit.calls` | `VideoSyncController` |

**Not instrumented (by design):** PortAudio callback / any RT audio path.

---

## 1. Song-switch timing breakdown

### Measured architecture (sync UI-thread order)

```text
activate.song.total
  ├─ activate.quiesce              engine.quiesce_output (if playing/stop)
  ├─ activate.arm_placeholder      Music lane "Loading…"
  ├─ activate.timeline             timeline.set_song + mark-line chrome
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
| `video.decode` (PyAV) | UI | **Primary Video Track cost** |

---

## 3. Video Track bottlenecks

Evidence from code (`video_sync.py`):

1. **Decode on Qt UI thread** — `_decode_and_emit` runs PyAV seek/decode where `update_position` is called (queued from engine ticks).  
2. **Throttle 30 Hz / 24 Hz** when Video Track is heavy — still competes with Timeline paints.  
3. **Frame fan-out** — Preview + Clean Output QImage conversion on emit (deduped if same ndarray).  
4. **Song switch** — `set_song` tears down decoders; `activate.video_land` may force a land decode.  
5. **Unrelated UI** — playhead path already dirties playhead strip; full Timeline + tall Video pixmap blit still hurts if `update()` is full-widget.

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

## 7. Implementation plan — Tasks 2–5 (evidence-based, not started)

| Task | Goal | Guardrails |
|------|------|------------|
| **2 — Song-switch readiness** | Raise `ram_hit`/`peaks_hit` rate; bound `activate.song.total`; clearer playback-ready | No engine redesign; keep quiesce; measure before/after |
| **3 — Video Track budget** | Cap UI-thread decode ms; optional worker decode queue; skip work when sinks off | AudioEngine remains sole clock; no second player |
| **4 — Cue List / chrome** | Shrink `activate.monitor_deferred`; defer non-visible work | No cue semantics change |
| **5 — Playhead / paint** | Keep partial dirty; reduce full paints with Video Track visible | No Timeline redesign; cadence constants documented |

Each task PR must include before/after `CUEPLAYER_PERF` spans on the same show file.

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

## 9. Performance Impact (this PR)

| Area | Impact |
|------|--------|
| **Playback** | None intended — semantics unchanged; diagnostics off by default |
| **Timeline FPS** | Negligible when `CUEPLAYER_PERF` off (counter increments are cheap); on = extra counters |
| **Song switch** | Same paths; optional spans only when enabled |
| **Video sync** | Same clock / throttle; decode wrapped only when enabled |
| **CPU** | ~0 when disabled; mild when enabled during play |
| **Memory** | Span lists grow until `perf.clear()` — clear between scenarios |

---

## READY FOR MEASURED PERFORMANCE OPTIMIZATION
