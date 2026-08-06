# Sprint 8 follow-up — Gap resume / PLAYBACK budget / Audio continuity

**Branch:** `cursor/sprint8-zoom-cue-video-state-028d`  
**Base:** `cursor/sprint8-cached-timeline-poster-028d` (PR #239)  
**PR:** #240  
**Status:** Ready for Windows GAP RESUME / PLAYBACK BUDGET / AUDIO CONTINUITY validation  
**(do not merge #239/#240 until Windows validation passes)**  
**Do not claim Video P0 solved.**

Preserved: current accepted Timeline mouse/static visuals, AudioEngine / sample clock,
Mark/Cue timestamps, Export, Preview state rules, zoom anchor, edge-Mark overlap,
no GPU decode, no broad decoder redesign.

## Why phantom WAITING_FRAME happened

Worker called `_note_resume_queued_frame()` for **every** play emit during RESUME,
including `None` / empty / timeline_gap results. UI `_on_async_frame_ready` returned
early on invalid frames **without clearing** the queued marker → watchdog deferred
for WAITING_FRAME → after 2s `callback_lost` → recovery churn. Evidence on
`c65e32b`: `empty_decode.reason.timeline_gap` ≫ resumes; `resume_waiting_frame_callback_lost`.

## Fix A — Request-level queued emit/ack

- Signal carries `request_id`.
- `QueuedResult` dict keyed by request_id (txn + media/scrub session + gen + req).
- On entry to `_on_async_frame_ready`, **ack matching delivery before any early return**.
- Only `valid_frame=True` (ndarray) counts as `valid_frame_waiting_for_present`.
- Counters: `queued_result_emitted/acknowledged/valid_frame/invalid_result/reject_reason/unacknowledged`.
- At txn end: emitted == acknowledged (force-ack leftovers).

## Fix B — Timeline gap terminates without recovery

- Before RESUME: classify Audio-clock target; no active clip → `VIDEO_TIMELINE_GAP`,
  `resume_not_required_timeline_gap` / `resume_terminal.intentional_gap`, return to PLAYBACK.
- Empty decode on a valid clip: ack, stay RESUME, resubmit latest (no 2s defer).

## Fix C — Stable PLAYBACK 24/30 Hz budget

- In PLAYBACK only: position ticks update latest target; submit at budget deadline.
- Do not throttle scrub preview, final land, or first RESUME frame.
- Counters: `engine_position_ticks`, `decode_submissions`, `frames_presented`,
  `budget_deferred`, `pending_latest_replacements`.

## Fix D — Audio continuity measurement (no clock change)

- PortAudio callback records underflow / interval / exec / deadline-miss without
  file I/O or extra locks.
- Miss windows sample `media_load_probe` play-decode + video-audio window counts.
- Published into PERF report via `publish_audio_continuity_to_perf()`.

## Windows validation

### 1. PERF OFF

```powershell
Remove-Item Env:CUEPLAYER_PERF -ErrorAction SilentlyContinue
cd <clone>
git fetch origin
git checkout cursor/sprint8-zoom-cue-video-state-028d
git pull
.\.venv\Scripts\python.exe -m cueplayer.app
```

Sparse 30s · dense 30s · sparse→dense→sparse ×3. Note whether Audio stutters.

### 2. PERF ON

```powershell
$env:CUEPLAYER_PERF = "1"
.\.venv\Scripts\python.exe -m cueplayer.app
```

Same operations → Tools → Write Performance Report.

### Pass only if

- Dense-region Video continues every time
- No invalid/empty result remains as WAITING_FRAME
- Timeline gaps do not enter frame-required recovery
- No first-playback-frame latency > 1s; no multi-second Video freeze
- Stable playback decode submissions near 24/30 Hz (not ~51 Hz)
- Audio continuous with PERF off and on
- Audio deadline/underflow counters show no recurring misses
- No AudioEngine timing / sample-clock change

READY FOR WINDOWS GAP RESUME / PLAYBACK BUDGET / AUDIO CONTINUITY VALIDATION
