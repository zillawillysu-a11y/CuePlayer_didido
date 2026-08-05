# Dense Mark Region Performance (Sprint 8 Task 2)

**Branch:** `cursor/sprint8-dense-mark-perf-028d`  
**Status:** instrumentation + indexed lookup + bounded NOW/Cue updates  
**Does not change:** Video decoder, AudioEngine, Export, Timeline feel goals

## Hypothesis

Windows freezes that remain after deterministic seek correlate with **dense Cue
regions** (~10 Marks/second), not with missing Video. `ui.position_fanout`
mean ~9.7 ms / max ~32 ms already exceeds a 16.7 ms frame budget.

## A/B measurement (same Song + Video)

| Region | How to choose |
|--------|----------------|
| **A Sparse** | 10 s with few/no Marks |
| **B Dense** | stress zone with ~10 Cues/s |

For each region run: normal play, paused seek, playing seek, slow scrub,
release+resume. Keep `CUEPLAYER_PERF=1` and dump Tools → Write Performance Report.

### Sub-spans (position fan-out)

`timeline.set_position`, `mark.lookup_ms`, `mark.geometry_ms`, `mark.paint_ms`,
`now_card.position_sync_ms`, `cue_list.position_sync_ms`,
`overview.position_sync_ms`, `monitor.position_sync_ms`,
`remote.position_sync_ms`, `video.schedule_ms`, `repaint.request_dispatch`,
`ui.position_fanout.total_ms`, `video.frame_ready_to_present_ms`

### Density notes

`mark.total_count`, `mark.visible_count`, `mark.count_in_current_second`,
`mark.crossings_per_position_update`, `timeline.zoom_pps`,
`ui.position_fanout.slow_*` (samples ≥ 16.7 ms correlated with Song Time +
nearby Mark count + whether Video was WAITING_FRAME)

## Code changes (targeted, not speculative Video work)

1. **Indexed Mark lookup** (`Song.mark_index_at_or_before` / bisect) — O(log n)
   instead of scanning every mark before the playhead.
2. **Viewport Mark paint** — only marks in visible time range.
3. **NOW card** — skip rebuild/fit when active Cue set unchanged; Cue List
   follow still runs (early-outs on same row).
4. **Fan-out sub-spans** for Windows A/B proof.

Video decoder / seek path intentionally untouched in this PR.

## Windows stress instructions

```powershell
$env:CUEPLAYER_PERF = "1"
cd C:\Users\willy\Projects\CuePlayer_v2
git fetch origin
git checkout cursor/sprint8-dense-mark-perf-028d
git pull
.\.venv\Scripts\python.exe -m cueplayer.app
```

1. Open the Song that has the ~10 Cues/s stress region.
2. Play through a **sparse** 10 s → note report / feel.
3. Play / seek / scrub through the **dense** region → note report / feel.
4. Tools → Write Performance Report… and paste the
   `Dense Mark / position-fanout (A/B)` section.

Compare sparse vs dense: `ui.position_fanout` mean/max, `now_card.*`,
`mark.paint_ms`, `video.schedule_ms`, `slow_samples` + `slow_marks_near`.

READY FOR WINDOWS DENSE MARK REGION VALIDATION
