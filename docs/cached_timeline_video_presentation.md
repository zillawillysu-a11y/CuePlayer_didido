# Cached Timeline / Video Presentation (Sprint 8 measured fix)

**Branch:** `cursor/sprint8-cached-timeline-poster-028d`  
**Follow-up:** `cursor/sprint8-zoom-cue-video-state-028d` (zoom visual / Cue follow / video states) — see `docs/sprint8_zoom_cue_video_state.md`  
**Status:** PART A Mark backdrop cache + PART B zoom coalesce + PART C activation poster  
**Does not change:** AudioEngine, Cue semantics, Export, Video seek SM broadly, zoom anchor

## Windows-confirmed root causes

| ID | Failure | Evidence |
|----|---------|----------|
| A | Dense Mark freeze | `mark.paint_ms` mean ~7 / max ~24; cProfile `_paint_marks*` ~2.0s; `draw_marker_shape` 33k |
| B | Video lag behind Timeline | `video.frame_ready_to_present_ms` mean ~289 / max ~2063 |
| C | ~7s black Preview on open | `empty_widget_visible_ms` max ~6877 |

Indexed Mark lookup was **not** the remaining bottleneck.

## Architecture after this fix

**STATIC/CACHEABLE backdrop (QPixmap):** waveform, ruler, lanes, **Mark stems/shapes/labels**  
**DYNAMIC overlay:** playhead, selection/hover/drag Marks only, scrub chrome, loop

**Zoom (initial):** raw wheel → latest target + temporary scale of cached pixmap → debounce (~64 ms) → one quality rebuild  

**Zoom (follow-up branch):** scale **spatial** cache only; Cue Notes / seconds / glyphs stay fixed screen-space size via annotation sprites; debounce **140 ms**; atomic cache swap (no blank flash).

**Activation (follow-up):** gate Loading on `VALID_VIDEO_TARGET_PENDING` only — not `NO_VIDEO_FOR_SONG` / `VIDEO_TIMELINE_GAP`.

**Diagnostics:** VIDEO_SM file I/O buffered (was ~1.17s of profile time from per-event opens).

## Windows validation

```powershell
$env:CUEPLAYER_PERF = "1"
cd C:\Users\willy\Projects\CuePlayer_v2
git fetch origin
git checkout cursor/sprint8-zoom-cue-video-state-028d
git pull
.\.venv\Scripts\python.exe -m cueplayer.app
```

Prefer the follow-up branch above for the three remaining UX failures. Original #239 checklist:

A. Open Video song → poster/loading immediately; no 6–7s empty black  
B. Play dense Mark region → Video keeps updating  
C. Zoom 10s → responsive Timeline; Video may drop frames but no multi-second catch-up  
D. Repeat sparse + dense  

Dump Tools → Write Performance Report. Check section **Cached Timeline / Zoom / Activation Poster**:

- `timeline.mark_backdrop.cache_hit` ≫ rebuilds during play  
- `draw_marker_shape_count` grows on rebuilds, not every play tick  
- `timeline.zoom.raw_events` ≫ `final_rebuilds`  
- `video.activation_poster.source` set; `empty_widget_visible_ms` near 0  
- `video.frame_ready_to_present_ms` mean/max down vs prior ~289 / ~2063  

Optional: Tools → Profile UI 5s in dense region — `_paint_marks_impl` should no longer dominate.

READY FOR WINDOWS CACHED TIMELINE / VIDEO PRESENTATION VALIDATION
