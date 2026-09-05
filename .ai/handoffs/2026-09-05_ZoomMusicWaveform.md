# Music waveform zoom geometry

Date: 2026-09-05. Branch: `cursor/technical-audit-0815-028d`.

## Task objective
Remove cached raster distortion from the Music waveform during wheel zoom.

## What was implemented
Repaint only the visible Music band/beat grid from current peak/raw resolution
over the transformed spatial cache. Restore fixed-size annotations afterwards.
Use ceil coverage for partially intersecting pixel-end buckets.

## Files changed
`src/cueplayer/ui/timeline_widget.py`, `tests/ui/test_zoom_waveform_geometry.py`,
`docs/audit/2026-09-05/zoom-renderer.json`, AI report/handoff pointers.

## Architecture decisions
Retain cached other layers and debounce; no decode or full cache rebuild in the
new band repaint. No playback PCM/clock/routing changes. Video/LTC lane preview
geometry is not claimed fixed by this Music-band slice.

## Tests performed
Before fix: 3 failures / 1 pass in geometry/bucket tests. After fixes and DPR
coverage: 25 UI tests passed (3 warnings). Pixel comparisons match direct render
at zoom 150/200/350 and DPR 1/1.5/2. DPR blit, pan, fonts/overlay/keep-zoom passed.
Inspected synthetic rendered Music-band PNG. Synthetic three-hour peak-only,
1200px/DPR1 warm band paint: medians 5.1–7.9ms, p95 6.5–10.0ms across four PPS.
This excludes decoding, complete Timeline paint, physical display and hardware
callback load; it does not certify overall 60Hz GUI performance.

## Remaining issues
Full Timeline performance requires real workload. Video/LTC lane zoom, stereo
phase cancellation, video waveform batch gaps, full PCM RAM, ASIO physical pitch/
timing and existing full-suite native/UI failures remain open.

## Suggested next task
Fix sequential video waveform batch carry and add real PyAV continuity tests;
preserve PTS and source coverage without changing playback decoder behavior.
Continue independent work while affected ASIO driver clarification is pending.
