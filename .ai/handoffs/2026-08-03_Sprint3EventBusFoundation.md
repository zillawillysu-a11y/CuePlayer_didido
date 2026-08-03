# Handoff — Sprint 3 Task 3: Event Bus Foundation

**Date:** 2026-08-03  
**Branch:** `cursor/sprint3-event-bus-foundation-028d`  
**Base:** `cursor/sprint3-remote-boundary-028d`

## Done

- `cueplayer.core.EventBus` with `subscribe` / `unsubscribe` / `publish`
- Unit tests in `tests/core/test_event_bus.py`
- Architecture + CHANGELOG updated
- No adopters; no UI / service behavior changes

## Not done (intentionally)

- Playback / ShowSession / Project / Settings migration onto the bus
- Qt signal replacement
- Async / sticky / replay / priorities / threading / networking

## Next

Sprint 3 Task 4 — Playback events.

## Suite

- EventBus unit: **10 passed**
- Full: **929 passed**, **16 failed** (pre-existing Linux/env; unchanged failure set)

## Marker

READY FOR PLAYBACK EVENTS
