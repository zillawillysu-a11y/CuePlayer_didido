# Next task

Allocation repair is complete: Effect stride is configurable (default 100), current defaults migrate safely, and the View page exposes working shared allocation controls. Remaining View work is drag/resize and Pool-type persistence.

**Status:** Queued — awaiting human start
**Type:** MA Export content selection and interactive View editor
**Updated:** 2026-08-08
**Workflow:** `READ → PLAN → IMPLEMENT → REPORT + HANDOFF → STOP`

## Current task

Finish the approved production MA Export interaction model by adding per-song Main/Button content selection and an interactive persisted Screen 3 View Layout editor.

## Requirements

- Expand each song to select Main and individual Button content.
- Reflect selections in Registry, Review, generated Sequences, and Timecode.
- Keep explicit Song Order and Unicode display names.
- Keep Screen 3 permanently fixed at 16 × 8.
- Allow Pool windows to be selected, dragged, and resized by whole cells.
- Pool titles consume one cell and never overflow.
- Support the approved MA2 Pool type list.
- Allow Fixed or Per Song allocation per Pool with Pool Start and Reserved Slots Per Song.
- Default Per Song Effects reservation to 100, minimum 1.
- Persist the shared layout with the project and validate overlaps/bounds.
- Reuse existing exporters and production Registry/Console synchronization.
- Do not implement Telnet in this task.
- Do not touch `startup_error.txt`.

## Done when

Focused UI/domain/persistence/exporter tests prove content filtering, drag/resize grid invariants, fixed/per-song allocation, Unicode round-trip, and export review consistency.
