# Handoff — Sprint 5 Task 5: Anchor Apply / Commit

**Date:** 2026-08-03  
**Branch:** `cursor/sprint5-anchor-apply-028d`  
**Base:** `cursor/sprint5-anchor-computation-028d`

## Done

- Apply commits `draft_offset` → `SongVariant.anchor_offset` via undo command
- Dirty + Undo/Redo; Cancel discards; Reset draft-only
- Marks never move; docs §22 + CHANGELOG

## Produce summary

1. **Commit flow** — draft → `SetVariantAnchorOffsetCommand.redo` → `offset_committed` → MainWindow undo + dirty  
2. **Undo coverage** — domain + UI tests restore offset; marks fixed  
3. **Remaining debt** — Preview session, duration chips, waveform indicator  
4. **Risks** — Preview expectation; applied offset used on next seek  
5. **Task 6** — Align Anchors MVP (Preview + polish)

## Next

Align Anchors MVP (Preview session).

## Marker

READY FOR ALIGN ANCHORS MVP
