# Waveform peak precision

Date: 2026-09-05. Branch: `cursor/technical-audit-0815-028d`.

## Task objective
Fix confirmed peak LOD selection and omitted partial tail without changing audio.

## What was implemented
Select coarse-to-fine, choosing the coarsest bucket no wider than a screen pixel.
Include the final partial bucket without zero-padding its envelope. Handle tiny
and empty arrays. Repair old cache tails from saved mono instead of full decode.

## Files changed
`media/audio_loader.py`, `media/audio_disk_cache.py`,
`tests/media/test_waveform_peak_precision.py`, AI report/handoff pointers.

## Architecture decisions
Reuse existing pyramid/cache. No new DSP, PCM mutation, cache format rewrite or
UI clock change. Existing Unicode, routing and media workflows remain intact.

## Tests performed
Eight new cases failed before the fix. After fixing and adding legacy cache
coverage: 56 passed across peak precision, loader/cache, video artifacts/views,
high-zoom outline and DPR blit suites. 44.1/48/96k impulses included.

## Remaining issues
Raster zoom stretch, pixel-end bucket coverage, stereo phase cancellation and
video batch carry remain separate. Full-suite native/UI and ASIO hardware items
remain as recorded in prior handoffs. No professional-DAW smoothness claim yet.

## Suggested next task
Render the music waveform at current zoom resolution during the cached preview,
preserving cached non-waveform layers/annotations, and cover pixel-end buckets.
Validate rendered images and bounded viewport paint cost before committing.
