# Handoff: Timeline zoom rendering hardening

Date: 2026-09-06. Branch: `technical-audit-0815-028d`.

## Summary

Fixed two confirmed zoom-time rendering bugs in `src/cueplayer/ui/timeline_widget.py`:

1. LTC generator clip rects/text were baked into the stretchable "spatial" raster used
   during wheel-zoom preview (`_blit_zoom_preview`), so they got geometrically resampled
   along with the waveform. They are now excluded from that bake and repainted live every
   zoom-preview frame instead (mirroring how Marks/ruler labels already worked).
2. The Mark glyph sprites baked for zoom preview (`_bake_mark_annotation_sprites`) always
   drew a white selection-style outline regardless of actual selected/hovered state. Fixed
   to match the live-paint `ring = selected or hovered or dragging` logic.

A third reported artifact (track/lane header labels looking temporarily bold during zoom)
was audited but not isolated to a code defect — header text is confined to the
1:1-blitted header column in both zoom-preview and native-cache paths. See `.ai/REPORT.md`
for full detail and the suggested manual re-check now that 1 and 2 are fixed.

## What to do next

Nothing queued. If the user reports the header-label bold artifact still reproduces after
this fix, that needs its own fresh repro/audit — it is not explained by any code path
found in this session.

See `.ai/REPORT.md` for the full root-cause writeup, exact diffs, and tests.
