# Handoff: Ports package Step 0

**Date:** 2026-08-03  
**TaskName:** `PortsPackageStep0`  
**Branch:** `cursor/ports-package-step0-028d`  
**Audience:** ChatGPT / future Cursor review

---

## Task objective

Implement `ARCHITECTURE_TARGET` **step 0** with a strict interface-first approach:
create `src/cueplayer/ports/` containing only Protocol-based boundary interfaces
(no wiring, adapters, services, or behavior changes).

## What was implemented

- Added `cueplayer.ports` with Protocols: `PlaybackClock`, `AudioDevicePort` (+ `AudioOutputDeviceInfo`), `VideoDecoderPort`, `VideoAudioSource`, `FrameSink`, `ProjectStore`, `ShowExporter`, `RemoteHost`, `MediaJobQueue`, `SongSession`.
- Smoke tests under `tests/ports/`.
- Docs / NEXT_TASK advanced to step 1.

## Files changed

See `.ai/REPORT.md` for the full table (`src/cueplayer/ports/*`, `tests/ports/test_ports_package.py`, architecture + `.ai` updates).

## Architecture decisions

- Ports are typing-only seams for the strangler plan; no call sites.
- Domain types allowed in signatures; adapter packages must not be imported by ports.
- `RemoteHost` kept minimal until step 2 wiring.
- Sample clock remains conceptually owned by `PlaybackClock` ↔ future `AudioEngine` adapter.

## Tests performed

- `import cueplayer.ports` OK
- `pytest tests/ports/test_ports_package.py` — 2 passed

## Remaining issues

- Protocols unimplemented in production (expected).
- Step 1 not started.
- Branch base may lag release tip; merge carefully with 1.0.6 lines.

## Suggested next task

**Step 1 — `cue_list_columns` → domain + shims; persistence must not import ui.**
