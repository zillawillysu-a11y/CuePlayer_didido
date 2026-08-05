# Dense Mark Instrumentation Fix (Sprint 8 Task 2)

**Branch:** `cursor/sprint8-perf-instrumentation-fix-028d`  
**Status:** fix empty A/B dumps — no Video/AudioEngine/Export changes  
**STOP:** obtain valid measurements before any further optimization

## Why the previous Dense Mark report was empty

Root cause: scrub/seek chrome used `_on_scrub_preview`, which updated
transport / NOW / Cue List **without** `ui.position_fanout` spans.

Windows sessions that are scrub-heavy (paused seek, playing seek, slow scrub,
release) therefore dumped:

- `ui.position_fanout.calls = 0`
- all Dense Mark spans `(none)`

while `video.seek.*` attrs still looked live (seek runs on the video worker path).

Also: `session-start` / `after-activate` auto-flushes must **not** be used for
Dense Mark A/B — they often precede play/scrub.

## Fix

1. Scrub preview shares the same fan-out instrumentation (`ui.position_fanout` +
   `ui.scrub_fanout` + `mark.lookup_ms` + monitor/transport spans).
2. Report includes **INSTRUMENTATION LIVE CHECK** (OK vs INVALID).
3. Tools → Write Performance Report dialog shows call counts and warns on
   invalid dumps.
4. Tools → Profile UI 5s (cProfile) for sparse vs dense when spans are still
   inconclusive.
5. Seek telemetry adds `keyframe_pts`, `keyframe_distance_s`, `gop_frames_estimate`.

## `video.seek.frames_to_target = 88` explained

Decoder policy (`MediaDecoder.frame_at`):

1. PyAV keyframe seek (`any_frame=False`, `backward=True`) lands on the
   **preceding keyframe**.
2. Decode-forward until PTS reaches the target.
3. `frames_to_target` counts frames decoded in that forward loop.

So **88 frames after seek is expected** for long-GOP H.264 test media:

| Assume FPS | ≈ GOP length |
|------------|--------------|
| 24 fps     | ~3.7 s       |
| 30 fps     | ~2.9 s       |
| 60 fps     | ~1.5 s       |

Check in the report:

- `video.seek.keyframe_pts` — first decoded PTS after seek (≈ keyframe)
- `video.seek.keyframe_distance_s` — `requested - keyframe_pts`
- `video.seek.gop_frames_estimate` — same as frames_to_target

This is **not** evidence of Mark-density coupling. Do not treat 88 as a decoder
bug unless `keyframe_distance_s` is tiny while frames stay huge (then investigate).

## Windows validation (required)

```powershell
$env:CUEPLAYER_PERF = "1"
cd C:\Users\willy\Projects\CuePlayer_v2
git fetch origin
git checkout cursor/sprint8-perf-instrumentation-fix-028d
git pull
.\.venv\Scripts\python.exe -m cueplayer.app
```

1. Open the Song + Video with sparse and dense Mark regions.
2. **Play** sparse 10 s, then dense 10 s (not scrub-only).
3. Also scrub once through each region.
4. Tools → **Write Performance Report…**
5. Dialog must show `LIVE CHECK: OK` and `ui.position_fanout.calls > 0`.
6. Paste the **last** `===== ... manual-dump =====` section, especially:
   - INSTRUMENTATION LIVE CHECK
   - Dense Mark / position-fanout (A/B)
   - `video.seek.keyframe_*` / `frames_to_target`

If LIVE CHECK is INVALID, dump is useless — play/scrub first and dump again.

Optional: Tools → Profile UI 5s while in dense region, then again in sparse;
compare `cueplayer_ui_profile.txt`.

## Non-goals this PR

- No Timeline zoom coalesce / Video decoder / AudioEngine / Export changes.
- No speculative Mark UI optimization until spans show real sparse vs dense cost.

READY FOR WINDOWS DENSE MARK INSTRUMENTATION VALIDATION
