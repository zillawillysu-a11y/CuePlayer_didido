# Sprint 8 follow-up — Zoom visual / Dense Cue follow / Video state

**Branch:** `cursor/sprint8-zoom-cue-video-state-028d`  
**Base:** `cursor/sprint8-cached-timeline-poster-028d` (PR #239)  
**Status:** Ready for Windows UX + PERF validation (do **not** merge #239 until this passes)

Does not change: AudioEngine / sample clock, Mark Cue timestamps, Export, Video seek SM direction, decoder architecture, GPU decode.

## Why #239 is not mergeable yet

Windows confirmed Mark paint + zoom Video responsiveness wins, but three user-visible failures remain.

| # | Failure | Evidence |
|---|---------|----------|
| 1 | Zoom scales Cue Notes / seconds / glyphs; snap-back; whole-UI flash | `raw_events` 557 vs `final_rebuilds` 103; rebuild mean ~54 ms |
| 2 | Dense Mark still freezes | `_mark_id_at_row` 103,339 calls / 5 s; Cue Monitor position-sync heavy |
| 3 | “Loading Video” on gaps / no-video songs | clip @ 0.456 s shows Loading for 0–0.456; no-video songs too |

## Fixes in this branch

### 1. Zoom visual stability
- Spatial cache (`_spatial_backdrop`): waveform / grid / clips / ticks — **scaled** during temporary zoom.
- Annotation sprites (`_mark_annotation_sprites`) + ruler labels: **fixed screen-space size**; X follows latest PPS.
- Atomic cache swap: rebuild off-screen, then assign — never clear between preview and final.
- Debounce **140 ms** (was 64) to cut final rebuild storms.
- Finish gesture: Timeline `update()` only; overview via throttled `view_changed`.

### 2. Dense Cue List follow
- `mark_id → row` map rebuilt in `refresh_list`.
- Position ticks use O(1) `_row_for_mark_id` (no full-table scan).
- Early-out when Mark ID + target row unchanged (no highlight / scroll / layout).
- NOW highlight only paints changed rows.
- Report: `cue_list.mark_id_at_row.calls` and `cue_list.position_sync_ms` in perf dump.

### 3. Video Preview states
| State | UI |
|-------|----|
| `NO_VIDEO_FOR_SONG` | Neutral / no Loading |
| `VIDEO_TIMELINE_GAP` | Intentional blank; no Loading; no early poster |
| `VALID_VIDEO_TARGET_PENDING` | Loading / poster allowed |
| `VALID_VIDEO_FRAME` | Normal present |

- Gate activation on active clip/path.
- `last_valid` only same clip + media session.
- Gaps / no-video do **not** open `empty_widget_visible_ms`.
- `first_valid_frame_after_song_activate_ms` only for a real valid frame of the current session.

## Windows validation

```powershell
$env:CUEPLAYER_PERF = "1"
cd C:\Users\willy\Projects\CuePlayer_v2
git fetch origin
git checkout cursor/sprint8-zoom-cue-video-state-028d
git pull
.\.venv\Scripts\python.exe -m cueplayer.app
```

1. **Zoom 10 s continuous** — Video responsive; Cue Note / seconds font size stable; no snap-back; no whole-window flash; zoom anchor unchanged.
2. **Dense Mark ≥ 30 s** — Audio / playhead / Video continue; Cue List follows; no complete freeze. Dump `_mark_id_at_row.calls` + Cue Monitor position-sync before/after.
3. **Video matrix** — no-video song: no Loading; clip @ 0.456 s: no Loading in 0–0.456; valid pending: Loading OK; switch songs: no stale frame.

Do **not** claim Dense Mark P0 solved until this Windows pass succeeds.

READY FOR WINDOWS ZOOM VISUAL / DENSE CUE FOLLOW / VIDEO STATE VALIDATION
